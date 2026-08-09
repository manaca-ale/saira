#!/usr/bin/env python3
"""Agente de captura SAIRA para Raspberry Pi (relay de câmera IP).

Substitui o papel da ESP32 (firmware/espcam-saira/src/ipcam_relay.cpp):
busca o snapshot da câmera IP e repassa, byte a byte (pass-through, SEM
reencode), para o esp32-server na EC2. Mantém o mesmo contrato de rede,
então worker/backend não mudam para dispositivos legados.

Threads:
  - capture_loop   : busca snapshot, roda o motion gate (BGSUB streaming,
                     ver motion_gate.py) e decide o que sobe:
                       MOTION_ENABLED=off    -> 1 frame a cada CAPTURE_INTERVAL
                       MOTION_ENABLED=shadow -> uploads legados; gate só loga
                                                e arquiva clipes de eventos
                       MOTION_ENABLED=on     -> burst durante eventos (com
                                                event_id/event_state no form),
                                                heartbeat esparso no idle
  - config_loop    : poll de /device/<id>/config.txt (ETag) e aplica
                     timer_delay_ms / ip_cam_* / pile_zone_polygon / tuning
                     do gate em runtime, sem reiniciar.
  - command_loop   : long-poll de /device/<id>/poll; comandos com argumento
                     usam a convenção "CMD_NAME:<arg>":
                       CMD_VIDEO_CLIP            -> exporta o ring recente
                       CMD_VIDEO_CLIP:<event_id> -> sobe o clipe da CADEIA do
                                                    evento (costurado)
                       CMD_PERSIST_CLIP:<event_id> -> cadeia RAM -> SD
                       CMD_BULK_UPLOAD           -> envia o spool como TLV
  - maintenance    : retenção/orçamento dos clipes no SD (ClipStore.prune).

Clipes de evento: ver clip_store.py (RAM-first; SD quando o worker confirma
UM membro da cadeia — os vizinhos vão junto — ou quando um evento fecha
vizinho de clipe já confirmado; upload só quando a plataforma requisita).

Hook de teste: SIGUSR1 injeta um evento sintético (~10s de burst + arquivo
de clipe), útil para validar o pipeline sem movimento real.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import socket
import struct
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from config import (
    Config,
    MIN_ANALYZE_INTERVAL_S,
    MIN_CAPTURE_INTERVAL_S,
    load_config,
)

log = logging.getLogger("saira-agent")

UPLOADED_SUFFIX = ".uploaded"
SYNTHETIC_EVENT_SECONDS = 10.0
WARMUP_UPLOAD_INTERVAL_S = 5.0  # warm-up sobe menos denso que burst de evento
MAINTENANCE_INTERVAL_S = 6 * 3600
# Intervalo mínimo entre leituras do zoom óptico para a telemetria. O zoom só
# muda por comando (atualizamos o cache de graça no CMD_ZOOM), mas a câmera pode
# resetar num power-cycle, então relemos de tempos em tempos. Espaçado de
# propósito: o httpd da câmera (porta 80) colapsa sob RAJADA, não sob 1 GET/min.
ZOOM_REFRESH_S = 60.0
# Teto DURO da janela ao vivo, POR COMANDO. A plataforma renova um lease curto
# enquanto o operador estiver presente; se ela (ou a rede) morrer, o dispositivo
# se apaga sozinho em no máximo isto. É o último backstop de consumo de 4G, e o
# único que não depende de nada mais estar vivo.
LIVE_MAX_SECONDS = 120.0
# Circuit-breaker do fallback HTTP (snapshot.cgi na porta 80). A porta 80 da
# câmera flapa muito quando ela oscila/subtensão (~50% 404 na pi-cam-001); sem
# o breaker o capture_loop martelava a porta a cada ciclo (~2s), gerando
# centenas de erros. Após N falhas consecutivas o breaker ABRE por um cooldown
# com backoff exponencial (base -> teto); enquanto aberto o HTTP é pulado (o
# RTSP segue como primário). Um probe half-open no fim do cooldown fecha
# (recupera) ou reabre com backoff maior.
HTTP_BREAKER_FAILS = 3       # falhas consecutivas do HTTP para abrir o breaker
HTTP_BREAKER_BASE_S = 30.0   # cooldown inicial ao abrir
HTTP_BREAKER_MAX_S = 600.0   # teto do backoff (10 min)
# Referência em que os polígonos são desenhados (igual ao motion_gate).
POLYGON_REF_W = 1280
POLYGON_REF_H = 720
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
# Frames que o CMD_CALIBRATE joga fora antes de medir: o MOG2 da sonda nasce
# vazio e acusa a zona inteira como foreground até convergir. Medido com frames
# reais da pi-cam-001: frame 0 = 100% da zona, frames 1-3 assentando, 4+ = 0.
# 10 dá folga sobre isso sem comer a janela (20s @1Hz ainda deixa 10 amostras).
_CALIB_SETTLE_FRAMES = 10


def _percentile(vals: list[int], p: float) -> int:
    """Percentil p (0..1) por nearest-rank. Lista vazia -> 0."""
    if not vals:
        return 0
    ordered = sorted(vals)
    idx = int(round(p * (len(ordered) - 1)))
    return ordered[idx]


def _cfg_parse(kv: dict, rej: dict, key: str, cast, scale: float = 1.0):
    """Parseia kv[key]; registra rejeição (e devolve None) se não casar o tipo."""
    raw = kv[key]
    try:
        val = cast(raw)
    except (ValueError, TypeError):
        rej[key] = raw
        return None
    return val * scale if scale != 1.0 else val


def _cfg_num(kv: dict, rej: dict, key: str, lo, hi, cast, scale: float = 1.0):
    """Valida em [lo,hi]; REJEITA fora da faixa (protege contra fat-finger em
    thresholds/tamanhos)."""
    val = _cfg_parse(kv, rej, key, cast, scale)
    if val is None:
        return None
    if (lo is not None and val < lo) or (hi is not None and val > hi):
        rej[key] = kv[key]
        return None
    return val


def _cfg_clamp(kv: dict, rej: dict, key: str, lo, hi, cast, scale: float = 1.0):
    """Parseia e CLAMPA em [lo,hi] (knobs de cadência: clampar é inofensivo e
    preserva a UX legada de piso/teto)."""
    val = _cfg_parse(kv, rej, key, cast, scale)
    if val is None:
        return None
    return max(lo, min(hi, val))


def sd_notify(state: str) -> None:
    """Envia uma notificação ao systemd (Type=notify / WatchdogSec) via o
    socket UNIX em $NOTIFY_SOCKET. No-op fora do systemd. Sem dependência."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):  # namespace abstrato
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(addr)
            sock.sendall(state.encode("utf-8"))
    except OSError:
        pass  # melhor esforço; nunca derruba o agente


def setup_logging(cfg: Config) -> None:
    """Console (journal) + arquivo rotativo, para o CMD_GET_LOGS poder ler o
    próprio log recente sem depender de journalctl/permissões."""
    root = logging.getLogger()
    root.setLevel(cfg.log_level)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    )
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        cfg.log_file.parent.mkdir(parents=True, exist_ok=True)
        fileh = RotatingFileHandler(
            cfg.log_file, maxBytes=cfg.log_max_bytes,
            backupCount=cfg.log_backup_count, encoding="utf-8",
        )
        fileh.setFormatter(fmt)
        root.addHandler(fileh)
    except OSError as exc:  # disco cheio / permissão — segue só com journal
        log.warning("Sem log em arquivo (%s): %s", cfg.log_file, exc)


class Agent:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._stop = threading.Event()

        # Estado de runtime mutável por config remota (protegido por lock).
        self._lock = threading.Lock()
        self._interval = cfg.capture_interval_s  # cadência legada/shadow
        self._cam_url = cfg.ip_cam_url
        self._cam_user = cfg.ip_cam_user
        self._cam_pass = cfg.ip_cam_pass
        self._cam_auth = cfg.ip_cam_auth
        self._motion_mode = cfg.motion_enabled if cfg.motion_enabled in (
            "off", "shadow", "on") else "off"
        self._idle_analyze_interval = cfg.idle_analyze_interval_s
        self._burst_interval = cfg.burst_upload_interval_s
        self._heartbeat_interval = float(cfg.heartbeat_interval_s)
        self._event_min_residual_px = cfg.pi_event_min_residual_px

        # Sessões HTTP persistentes (keep-alive evita handshake por frame).
        self._cam_session = requests.Session()
        self._ec2_session = requests.Session()
        self._ec2_session.headers.update({"X-Device-Id": cfg.device_id})

        cfg.spool_dir.mkdir(parents=True, exist_ok=True)

        # Motion gate (lazy: criado só se o modo pedir e o cv2 importar).
        self._gate = None
        if self._motion_mode != "off":
            self._gate = self._build_gate()
            if self._gate is None:
                self._motion_mode = "off"

        # Clip store (sempre disponível: CMD_VIDEO_CLIP:<id> e SIGUSR1
        # funcionam mesmo com o gate desligado).
        from clip_store import ClipStore

        self._clips = ClipStore(
            seg_dir=cfg.video_seg_dir,
            archive_dir=cfg.archive_dir,
            clips_dir=cfg.clips_dir,
            archive_max_bytes=cfg.archive_max_bytes,
            clip_seconds=cfg.video_clip_seconds,
            seg_seconds=cfg.video_seg_seconds,
            pre_roll_seconds=cfg.pre_roll_seconds,
            tail_seconds=cfg.tail_seconds,
            retention_days=cfg.clip_retention_days,
            chain_enabled=cfg.clip_chain_enabled,
            chain_gap_s=cfg.clip_chain_gap_s,
            chain_span_s=cfg.clip_chain_span_s,
            chain_max_s=cfg.clip_chain_max_s,
            clips_max_bytes=cfg.clips_max_bytes,
            event_max_s=cfg.event_max_s,
        )

        # Rastreio de eventos correntes (para timestamps do clipe).
        self._event_start_ts: dict[str, float] = {}
        self._last_upload_at = 0.0

        # Snapshot via RTSP (latest.jpg do cam-rtsp-buffer.sh).
        self._last_snapshot_mtime = 0.0
        self._stale_snapshot_warned = False

        # Circuit-breaker do fallback HTTP (só o capture_loop mexe nestes campos).
        self._http_fail_count = 0
        self._http_breaker_until = 0.0  # monotonic; > now => porta 80 em cooldown
        self._http_backoff_s = 0.0
        self._http_last_error = ""

        # Evento sintético (SIGUSR1).
        self._synthetic_id: Optional[str] = None
        self._synthetic_start = 0.0
        self._synthetic_until = 0.0
        self._synthetic_start_sent = False

        # Modo ao vivo (CMD_LIVE) — janela temporal para instalação em campo.
        # Vive na live_loop, uma thread PRÓPRIA: o upload ao vivo não passa pelo
        # capture_loop de propósito. O gate raciocina em FRAMES (consec_start) e
        # aprende POR FRAME (lr_idle), então acelerar a captura durante o live o
        # deixaria mais sensível e mudaria a adaptação do fundo — justo quando o
        # técnico está se mexendo na frente da lente. Isso abriria eventos falsos
        # com event_id e custaria Gemini durante a instalação.
        self._live_until = 0.0
        # mtime PRÓPRIO. Não reusar _last_snapshot_mtime: ele é da thread de
        # captura (sentinela _SAME_FRAME). Duas threads escrevendo nele criam uma
        # race onde o live "consome" o frame e o gate para de receber dados.
        self._live_last_mtime = 0.0
        self._live_interval = 1.0

        # Ref_pré: ring dos últimos frames de IDLE (sem evento). Congela no
        # instante da intrusão (não atualiza durante evento), então ring[0] é a
        # cena ANTES do ator. No início do evento sobe esse "antes" como primeiro
        # frame, dando à nuvem o par antes/depois para julgar incremento na pilha.
        self._frame_ring: list[bytes] = []
        self._send_pre_frame = cfg.pi_send_pre_frame

        # Lote de frames do evento (EVENT_BATCH_SIZE>=2): acumula e sobe num
        # único POST /upload-batch a cada N frames ou no fim do evento.
        self._event_batch: list[tuple[bytes, str, str]] = []  # (jpeg, event_id, state)
        self._event_batch_size = cfg.event_batch_size  # hot-reload via config

        # ----- observabilidade / auto-cura (deploy remoto) -----------------
        self._start_monotonic = time.monotonic()
        self._heartbeat_mode = cfg.heartbeat_mode
        self._snapshot_source = cfg.snapshot_source
        self._log_level = cfg.log_level
        self._safe_mode = False
        # Saúde de captura/câmera (separar "Pi muda" de "câmera caída").
        self._last_capture_ok_at = 0.0
        self._last_capture_source = "none"
        self._camera_ok = False
        # Zoom óptico atual (lente motorizada Intelbras), reportado na telemetria
        # para o painel exibir a posição REAL da lente. Lido da câmera com throttle
        # (ver ZOOM_REFRESH_S) para não martelar o httpd dela; atualizado de graça
        # após cada CMD_ZOOM. None = ainda não lido / câmera sem lente motorizada.
        self._last_zoom: Optional[float] = None
        self._last_zoom_read_at = 0.0
        self._last_fg_px = 0
        self._last_delta_px = 0
        # Eventos do dia (reseta na virada de data BRT-naive local).
        self._last_event_id: Optional[str] = None
        self._last_event_at = 0.0
        self._events_today = 0
        self._events_today_date = time.strftime("%Y-%m-%d")
        # Config: versão aplicada + chaves rejeitadas (vão p/ a telemetria).
        self._config_version = "0"
        # fg/delta/config_version do gate no disparo, por event_id — enviados
        # como form fields no upload do evento p/ o worker auditar o threshold.
        self._gate_stats_pending: dict[str, dict] = {}
        self._rejected_config: dict[str, str] = {}
        self._last_good_polygon = cfg.pile_zone_polygon
        # Watchdog: cada thread "bate" no topo da iteração.
        self._beats: dict[str, float] = {}
        # Pedido de re-anchor do gate (CMD_RECALIBRATE / mudança de enquadramento):
        # setado por qualquer thread, consumido pela thread de captura (dona do gate).
        self._recalibrate_requested = False
        self._disk_low = False

    def _build_gate(self):
        try:
            from motion_gate import MotionGate
        except ImportError as exc:
            log.error(
                "MOTION_ENABLED=%s mas cv2/numpy indisponíveis (%s) — "
                "caindo para modo legado", self._motion_mode, exc,
            )
            return None
        return MotionGate(
            history=self.cfg.pi_bgsub_history,
            var_threshold=self.cfg.pi_bgsub_var_threshold,
            shadow_threshold=self.cfg.pi_bgsub_shadow_threshold,
            min_px_active=self.cfg.pi_bgsub_min_px_active,
            delta_min_px=self.cfg.pi_bgsub_delta_min_px,
            delta_start_px=self.cfg.pi_bgsub_delta_start_px,
            consec_start=self.cfg.pi_bgsub_consec_start,
            lr_idle=self.cfg.pi_bgsub_lr_idle,
            lr_recover=self.cfg.pi_bgsub_lr_recover,
            warmup_seconds=self.cfg.warmup_seconds,
            event_end_quiet_s=self.cfg.event_end_quiet_s,
            event_max_s=self.cfg.event_max_s,
            recover_max_s=self.cfg.pi_bgsub_recover_max_s,
            polygon_json=self.cfg.pile_zone_polygon,
            device_id=self.cfg.device_id,
        )

    # ----- ciclo de vida -------------------------------------------------
    def stop(self, *_: object) -> None:
        log.info("Encerrando agente...")
        self._stop.set()

    def trigger_synthetic_event(self, *_: object) -> None:
        """SIGUSR1: injeta um evento de teste (burst + clipe), em qualquer modo."""
        now = time.time()
        if self._synthetic_id is not None:
            return
        self._synthetic_id = "evt-test-" + time.strftime(
            "%Y%m%d_%H%M%S", time.localtime(now)
        )
        self._synthetic_start = now
        self._synthetic_until = now + SYNTHETIC_EVENT_SECONDS
        self._synthetic_start_sent = False
        log.info("Evento sintético %s iniciado (SIGUSR1)", self._synthetic_id)

    def _beat(self, name: str) -> None:
        """Marca a thread como viva (consumido pelo watchdog)."""
        self._beats[name] = time.monotonic()

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.capture_loop, name="capture", daemon=True),
            threading.Thread(target=self.config_loop, name="config", daemon=True),
            threading.Thread(target=self.command_loop, name="command", daemon=True),
            threading.Thread(target=self.telemetry_loop, name="telemetry", daemon=True),
            threading.Thread(target=self.maintenance_loop, name="maint", daemon=True),
            threading.Thread(target=self.live_loop, name="live", daemon=True),
        ]
        now = time.monotonic()
        for name in ("capture", "config", "command", "telemetry"):
            self._beats[name] = now
        for t in threads:
            t.start()
        # Watchdog não é monitorado (é o monitor) e roda mesmo se uma thread cair.
        threading.Thread(target=self.watchdog_loop, name="watchdog", daemon=True).start()
        log.info(
            "Agente iniciado v=%s device=%s cam=%s -> %s (modo=%s, análise=%.1fs)",
            self.cfg.agent_version, self.cfg.device_id, self._cam_url,
            self.cfg.upload_url, self._motion_mode, self._capture_cadence(),
        )
        sd_notify("READY=1")
        sd_notify(f"STATUS=device={self.cfg.device_id} mode={self._motion_mode}")
        while not self._stop.is_set():
            self._stop.wait(1.0)
        for t in threads:
            t.join(timeout=5.0)

    def maintenance_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._clips.prune()
            except Exception:  # noqa: BLE001
                log.exception("Falha na manutenção de clipes")
            self._stop.wait(MAINTENANCE_INTERVAL_S)

    # ----- modo ao vivo --------------------------------------------------
    def _live_active(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) < self._live_until

    def live_loop(self) -> None:
        """Sobe frames a ~1 fps enquanto a janela do CMD_LIVE estiver aberta.

        Isolada do capture_loop de propósito (ver _live_until em __init__): não
        toca o gate, não muda _capture_cadence(), não interage com a lógica de
        movimento. O flagrante segue intacto enquanto o técnico olha a câmera.

        Teto de fps: o cam-rtsp-buffer só regrava o latest.jpg a partir de
        KEYFRAMES (-skip_frame nokey), ~1 a cada 1-2s. Pedir menos que isso não
        traz frame novo — daí o dedup por mtime em vez de subir o mesmo JPEG.
        """
        while not self._stop.is_set():
            self._beat("live")
            if not self._live_active():
                # Tick fino: um CMD_LIVE:0 tem que parar na hora, não no fim
                # do intervalo ao vivo.
                self._stop.wait(0.5)
                continue
            try:
                self._live_capture_once()
            except Exception:  # noqa: BLE001 - loop nunca pode morrer
                log.exception("Falha inesperada no ciclo ao vivo")
            self._stop.wait(max(0.5, self._live_interval))

    def _live_capture_once(self) -> None:
        # Evento real tem prioridade: os frames do evento já sobem com event_id
        # pelo capture_loop e o painel os mostra como "última imagem" (o servidor
        # varre a subárvore inteira do device). Subir aqui também dobraria o 4G
        # exatamente durante um evento.
        if self._gate is not None and self._gate.state in ("event", "warmup"):
            return
        try:
            mtime = self.cfg.snapshot_jpg.stat().st_mtime
        except OSError:
            return
        if not mtime or mtime == self._live_last_mtime:
            return  # sem keyframe novo — nada a subir
        data = self._fresh_local_snapshot()  # guard de idade embutido
        if not data:
            return
        self._live_last_mtime = mtime
        self._upload_live_frame(data)  # SEM event_id e SEM spool (ver docstring)

    def _upload_live_frame(self, data: bytes) -> bool:
        """Sobe UM frame ao vivo DIRETO, sem passar pelo spool.

        Não usar _spool_and_upload aqui é a correção de um bug real observado em
        campo: o spool é compartilhado com a thread de captura, e as duas drenam
        o mesmo backlog (_drain_backlog). Como o `.uploaded` só é marcado DEPOIS
        do POST, a captura lia a lista de pendentes antes da marca e reenviava o
        frame que o live acabara de subir — o mesmo arquivo ia 2× para a EC2,
        dobrando o 4G, que é exatamente o que o modo ao vivo existe para conter.

        Frames ao vivo são efêmeros: se um POST falhar, não há o que recuperar —
        o próximo keyframe vem em ~1s. Resiliência offline é requisito dos frames
        de EVENTO (que viram ocorrência), não da visualização em campo.
        """
        files = {"imageFile": ("snapshot.jpg", data, "image/jpeg")}
        t0 = time.monotonic()
        try:
            resp = self._ec2_session.post(
                self.cfg.upload_url, files=files, timeout=self.cfg.upload_timeout_s,
            )
        except requests.RequestException as exc:
            log.warning("Upload ao vivo falhou (frame descartado): %s", exc)
            return False
        if resp.status_code == 200:
            self._last_upload_at = time.time()
            log.info("Live OK (%d bytes, %dms)", len(data),
                     int((time.monotonic() - t0) * 1000))
            return True
        log.warning("Upload ao vivo HTTP %s", resp.status_code)
        return False

    def _handle_live_cmd(self, arg: str) -> None:
        """CMD_LIVE:<segundos> — abre/renova a janela ao vivo. CMD_LIVE:0 para.

        O deadline é SUBSTITUÍDO, não somado: renovar move o prazo, não acumula.
        """
        # safe_mode precisa ser checado AQUI: comandos não passam por
        # _apply_runtime_keys, que é o único ponto onde o kill-switch age. Sem
        # este guard, o safe_mode não seguraria o live.
        with self._lock:
            if self._safe_mode:
                log.warning("CMD_LIVE ignorado: safe_mode ativo")
                self._post_status("live_rejected_safe_mode")
                return
        try:
            secs = float(arg)
        except (TypeError, ValueError):
            log.warning("CMD_LIVE com argumento inválido: %r", arg)
            return
        secs = max(0.0, min(LIVE_MAX_SECONDS, secs))
        if secs <= 0:
            self._live_until = 0.0
            log.info("CMD_LIVE: modo ao vivo encerrado")
            return
        self._live_until = time.time() + secs
        log.info("CMD_LIVE: modo ao vivo por %.0fs (cadência %.1fs)",
                 secs, self._live_interval)

    # ----- captura -------------------------------------------------------
    def _capture_cadence(self) -> float:
        """Cadência do loop de captura conforme o modo/estado."""
        with self._lock:
            mode = self._motion_mode
            legacy = max(MIN_CAPTURE_INTERVAL_S, self._interval)
            analyze = max(MIN_ANALYZE_INTERVAL_S, self._idle_analyze_interval)
            burst = max(0.5, self._burst_interval)
        if mode == "off":
            return legacy if self._synthetic_id is None else burst
        if self._synthetic_id is not None:
            return burst
        if self._gate is not None and self._gate.state in ("event", "warmup"):
            return burst
        return analyze

    def capture_loop(self) -> None:
        # A cadência é reavaliada a CADA tick (0,5s): mudanças de config
        # remoto, início de burst ou evento sintético encurtam a espera em
        # andamento — com agendamento fixo, sair de um intervalo longo (ex.
        # câmera pausada) só valeria após o sleep atual inteiro.
        last_at = 0.0
        while not self._stop.is_set():
            self._beat("capture")
            interval = self._capture_cadence()
            now = time.monotonic()
            wait = (last_at + interval) - now
            if wait > 0:
                self._stop.wait(min(wait, 0.5))
                continue
            last_at = now
            try:
                self._consume_recalibrate()
                self._capture_once()
            except Exception:  # noqa: BLE001 - loop nunca pode morrer
                log.exception("Falha inesperada no ciclo de captura")

    def _consume_recalibrate(self) -> None:
        """Re-anchor do gate pedido por outra thread (CMD_RECALIBRATE / zoom /
        troca de IP). Só a thread de captura toca o gate, então o pedido é
        consumido aqui via flag."""
        if not self._recalibrate_requested:
            return
        self._recalibrate_requested = False
        if self._gate is not None:
            log.info("Re-anchor do gate (warm-up silencioso) por solicitação")
            self._gate.begin_warmup(silent=True)

    def _capture_once(self) -> None:
        data = self._fetch_snapshot()
        if not data:
            self._drain_backlog()
            return

        now = time.time()
        self._last_capture_ok_at = now
        self._camera_ok = True
        synthetic = self._poll_synthetic(now)
        if synthetic is not None:
            event_id, state = synthetic
            self._spool_and_upload(data, event_id=event_id, event_state=state)
            return

        with self._lock:
            mode = self._motion_mode
        if mode == "off" or self._gate is None:
            self._spool_and_upload(data)
            return

        decision = self._gate.process(data)
        self._last_fg_px = decision.fg_px
        self._last_delta_px = decision.delta_px
        if decision.action == "start" and not decision.is_warmup:
            self._event_start_ts[decision.event_id] = now
            self._note_event(decision.event_id, now)
            # Guarda os stats do disparo p/ anexar ao upload do evento.
            self._gate_stats_pending[decision.event_id] = {
                "gate_fg_px": str(decision.fg_px),
                "gate_delta_px": str(decision.delta_px),
                "gate_config_version": self._config_version,
            }
        if decision.action in ("start", "end"):
            log.info(
                "[gate:%s] %s %s fg_px=%d delta_px=%d reason=%s",
                mode, decision.event_id, decision.action,
                decision.fg_px, decision.delta_px, decision.reason or "-",
            )
        else:
            log.debug(
                "[gate:%s] %s state=%s fg_px=%d delta_px=%d",
                mode, decision.event_id or "-", decision.state,
                decision.fg_px, decision.delta_px,
            )

        if mode == "shadow":
            # Uploads continuam legados; o gate só loga e arquiva clipes.
            if decision.action == "end" and not decision.is_warmup:
                self._schedule_archive(decision.event_id, end_ts=now)
            if now - self._last_upload_at >= max(MIN_CAPTURE_INTERVAL_S, self._interval):
                self._spool_and_upload(data)
            return

        # ---- mode == "on" -------------------------------------------------
        # Mantém o ring do "antes": só atualiza FORA de evento (idle/recover),
        # congelando no instante da intrusão. ring[0] = frame mais antigo, que
        # precede os consec_start frames de gatilho, garantindo cena sem o ator.
        if decision.event_id is None and not decision.is_warmup:
            self._frame_ring.append(data)
            if len(self._frame_ring) > 4:
                self._frame_ring.pop(0)

        if decision.action == "end":
            # Pré-filtro transiente: a zona voltou à baseline (fg residual
            # baixo) => nada NOVO ficou; foi passagem. Marca "end_transient"
            # para o worker descartar sem custo de Gemini. Warm-up nunca é
            # transiente (é fail-open, sempre julga na nuvem).
            transient = (
                not decision.is_warmup
                and decision.fg_px < self._event_min_residual_px
            )
            state = "end_transient" if transient else "end"
            # Frame de fechamento sobe sempre (fecha o manifest no servidor).
            if self._event_batch_size >= 2 and not decision.is_warmup:
                # Enfileira o frame de fechamento: _queue_event_frame faz o
                # flush imediato do lote pendente ao ver o estado de "end".
                self._queue_event_frame(data, decision.event_id, state)
            else:
                self._spool_and_upload(data, event_id=decision.event_id, event_state=state)
            if not decision.is_warmup:
                self._schedule_archive(decision.event_id, end_ts=now)
            if transient:
                log.info(
                    "Evento %s transiente (fg_end=%d < %d) — não escala p/ Gemini",
                    decision.event_id, decision.fg_px, self._event_min_residual_px,
                )
            return

        if decision.event_id is not None and decision.action in ("start", "active"):
            batching = self._event_batch_size >= 2 and not decision.is_warmup
            # No início do evento real, sobe o "antes" (cena pré-intrusão) como
            # primeiro frame, dando à nuvem o par antes/depois. O frame do gatilho
            # (com o ator) vai logo em seguida.
            if (
                decision.action == "start"
                and not decision.is_warmup
                and self._send_pre_frame
                and self._frame_ring
            ):
                if batching:
                    self._queue_event_frame(self._frame_ring[0], decision.event_id, "start")
                else:
                    self._spool_and_upload(
                        self._frame_ring[0],
                        event_id=decision.event_id,
                        event_state="start",
                    )
            if batching:
                # Captura densa (cadência ~burst); o upload só ocorre a cada N
                # frames (flush dentro de _queue_event_frame), não por frame.
                state = "start" if decision.action == "start" else "active"
                self._queue_event_frame(data, decision.event_id, state)
                return
            min_gap = WARMUP_UPLOAD_INTERVAL_S if decision.is_warmup else max(
                0.5, self._burst_interval
            )
            if decision.action == "start" or now - self._last_upload_at >= min_gap:
                state = "start" if decision.action == "start" else "active"
                self._spool_and_upload(data, event_id=decision.event_id, event_state=state)
            return

        # idle/recover: no modo "image" sobe um frame esparso p/ o painel ter
        # thumbnail. O keepalive leve + telemetria de saúde é da telemetry_loop
        # (roda mesmo com a câmera caída, então "Pi muda" != "câmera offline").
        if self._heartbeat_mode == "image" and now - self._last_upload_at >= self._heartbeat_interval:
            self._spool_and_upload(data)

    def _note_event(self, event_id: Optional[str], now: float) -> None:
        """Atualiza contadores de evento para a telemetria (rollover diário)."""
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if today != self._events_today_date:
            self._events_today_date = today
            self._events_today = 0
        self._events_today += 1
        self._last_event_id = event_id
        self._last_event_at = now

    def _poll_synthetic(self, now: float) -> Optional[tuple[str, str]]:
        """Avança o evento sintético (SIGUSR1), devolvendo (event_id, state)."""
        if self._synthetic_id is None:
            return None
        event_id = self._synthetic_id
        if now >= self._synthetic_until:
            self._synthetic_id = None
            self._schedule_archive(event_id, end_ts=now, start_ts=self._synthetic_start)
            log.info("Evento sintético %s encerrado", event_id)
            return event_id, "end"
        if not self._synthetic_start_sent:
            self._synthetic_start_sent = True
            return event_id, "start"
        return event_id, "active"

    def _schedule_archive(
        self, event_id: str, *, end_ts: float, start_ts: Optional[float] = None
    ) -> None:
        """Agenda a cópia dos segmentos do ring após o tail (segmento fechado)."""
        if start_ts is None:
            start_ts = self._event_start_ts.pop(event_id, end_ts - 30.0)
        delay = self.cfg.tail_seconds + self.cfg.video_seg_seconds
        timer = threading.Timer(
            delay, self._archive_and_persist, args=(event_id, start_ts, end_ts)
        )
        timer.daemon = True
        timer.start()

    def _archive_and_persist(self, event_id: str, start_ts: float, end_ts: float) -> None:
        """Corpo do Timer pós-evento: arquiva o ring em RAM e, se o evento
        for vizinho de cadeia de um clipe já confirmado no SD, persiste na
        hora (persist_if_chained) — o worker nunca confirma individualmente
        os membros posteriores de uma ocorrência longa (foi assim que a
        saída de 17/07 se perdeu). Nunca levanta: a thread do Timer não tem
        handler."""
        try:
            if not self._clips.archive_event(event_id, start_ts, end_ts):
                return
            free = self._disk_free_mb(self.cfg.clips_dir)
            if free is not None and free < self.cfg.min_disk_free_mb:
                log.warning(
                    "Disco baixo (%s MB) — persistência por adjacência pulada (%s)",
                    free, event_id,
                )
                return
            self._clips.persist_if_chained(event_id)
        except Exception:  # noqa: BLE001
            log.exception("Falha no archive/persist do evento %s", event_id)

    # Sentinela: o keyframe do RTSP ainda é o mesmo do ciclo anterior —
    # pula o ciclo SEM cair para o snapshot HTTP (que é flaky).
    _SAME_FRAME = object()

    def _fetch_snapshot(self) -> bytes | None:
        source = self._snapshot_source
        if source in ("auto", "rtsp"):
            res = self._fetch_snapshot_rtsp()
            if res is Agent._SAME_FRAME:
                return None
            if res is not None:
                self._last_capture_source = "rtsp"
                return res
            if source == "rtsp":
                return None
        data = self._fetch_snapshot_http_guarded()
        if data is not None:
            self._last_capture_source = "http"
        return data

    def _fetch_snapshot_http_guarded(self) -> bytes | None:
        """Fallback HTTP com circuit-breaker (ver HTTP_BREAKER_*). Enquanto o
        breaker está aberto NÃO toca a porta 80 (evita o martelar que gerava
        centenas de erros); o RTSP segue como primário. Chamado só pelo
        capture_loop — os caminhos sob demanda (CMD_SNAPSHOT/CALIBRATE) usam o
        _fetch_snapshot_http direto de propósito (ação do operador ignora o
        breaker: ele pode ter acabado de consertar a câmera)."""
        now = time.monotonic()
        if now < self._http_breaker_until:
            return None  # breaker aberto: não martela a porta 80
        data = self._fetch_snapshot_http()
        if data is not None:
            if self._http_fail_count >= HTTP_BREAKER_FAILS:
                log.info("Fallback HTTP recuperado (%.0fs em cooldown) — breaker fechado",
                         self._http_backoff_s)
            self._http_fail_count = 0
            self._http_backoff_s = 0.0
            self._http_breaker_until = 0.0
            return data
        self._http_fail_count += 1
        if self._http_fail_count >= HTTP_BREAKER_FAILS:
            self._http_backoff_s = (
                HTTP_BREAKER_BASE_S if self._http_backoff_s <= 0
                else min(HTTP_BREAKER_MAX_S, self._http_backoff_s * 2)
            )
            self._http_breaker_until = now + self._http_backoff_s
            # Log só na transição/reabertura (1 por episódio), não por ciclo.
            log.warning(
                "Fallback HTTP: %d falhas consecutivas (%s) — pausando a porta 80 "
                "por %.0fs (RTSP continua primário)",
                self._http_fail_count, self._http_last_error or "?", self._http_backoff_s,
            )
        return None

    def _fetch_snapshot_rtsp(self):
        """Lê o JPEG mantido pelo cam-rtsp-buffer.sh a partir dos keyframes
        do RTSP (escrita atômica). Sem rede e sem o snapshot HTTP flaky da
        câmera; atualiza a cada GOP (~1-2s).

        Retorna bytes (frame novo), _SAME_FRAME (sem keyframe novo ainda) ou
        None (arquivo ausente/velho/corrompido — fallback HTTP no modo auto).
        """
        path = self.cfg.snapshot_jpg
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._warn_stale_snapshot("inexistente")
            return None
        age = time.time() - mtime
        if age > self.cfg.snapshot_max_age_s:
            self._warn_stale_snapshot(f"velho ({age:.0f}s)")
            return None
        if mtime == self._last_snapshot_mtime:
            return Agent._SAME_FRAME
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if len(data) < 500 or data[:2] != b"\xff\xd8":
            return None  # escrita atômica torna isso raro; trata como miss
        self._last_snapshot_mtime = mtime
        self._stale_snapshot_warned = False
        return data

    def _warn_stale_snapshot(self, why: str) -> None:
        """Loga uma vez por episódio (evita 1 warning a cada ciclo)."""
        if not self._stale_snapshot_warned:
            log.warning(
                "Snapshot RTSP %s (%s) — fallback HTTP; verifique saira-rtsp-buffer",
                why, self.cfg.snapshot_jpg,
            )
            self._stale_snapshot_warned = True

    def _fetch_snapshot_http(self) -> bytes | None:
        with self._lock:
            url, user, pwd, auth_mode = self._cam_url, self._cam_user, self._cam_pass, self._cam_auth
        attempts = (
            ["basic", "digest"] if auth_mode == "auto"
            else [auth_mode] if auth_mode in ("basic", "digest")
            else ["none"]
        )
        for mode in attempts:
            auth = None
            if mode == "basic":
                auth = HTTPBasicAuth(user, pwd)
            elif mode == "digest":
                auth = HTTPDigestAuth(user, pwd)
            try:
                resp = self._cam_session.get(url, auth=auth, timeout=self.cfg.cam_timeout_s)
            except requests.RequestException as exc:
                # DEBUG por tentativa: o episódio é logado 1× pelo circuit-breaker
                # (_fetch_snapshot_http_guarded) para não spammar a cada ciclo.
                self._http_last_error = type(exc).__name__
                log.debug("Erro ao buscar snapshot HTTP (%s): %s", mode, exc)
                return None
            if resp.status_code == 401 and auth_mode == "auto" and mode == "basic":
                continue  # tenta digest
            if resp.status_code != 200:
                self._http_last_error = f"HTTP {resp.status_code}"
                log.debug("Snapshot HTTP %s (%s)", resp.status_code, mode)
                return None
            body = resp.content
            if len(body) < 500 or body[:2] != b"\xff\xd8":
                self._http_last_error = f"corpo inválido ({len(body)}B)"
                log.debug("Snapshot HTTP inválido (%d bytes)", len(body))
                return None
            return body
        self._http_last_error = "401 (auth)"
        return None

    # ----- upload / spool ------------------------------------------------
    @staticmethod
    def _spool_name(ts: str, event_id: Optional[str], event_state: str) -> str:
        """Nome no spool carrega o metadado do evento para sobreviver a retry:
        "{ts}.jpg" (legado) ou "{ts}__{event_id}__{state}.jpg" (evento)."""
        if not event_id:
            return f"{ts}.jpg"
        return f"{ts}__{event_id}__{event_state or 'active'}.jpg"

    @staticmethod
    def _parse_spool_name(name: str) -> tuple[Optional[str], str]:
        """Extrai (event_id, event_state) do nome de spool, se presente."""
        stem = name[:-4] if name.endswith(".jpg") else name
        parts = stem.split("__")
        if len(parts) == 3:
            return parts[1], parts[2]
        return None, ""

    def _spool_and_upload(
        self, data: bytes, *, event_id: Optional[str] = None, event_state: str = ""
    ) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        frame_path = self.cfg.spool_dir / self._spool_name(ts, event_id, event_state)
        tmp = frame_path.with_suffix(".jpg.tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(frame_path)
        except OSError as exc:
            # Disco cheio / IO: degrada graciosamente (não derruba a thread).
            log.warning("Falha ao gravar frame no spool (%s) — descartado: %s",
                        frame_path.name, exc)
            tmp.unlink(missing_ok=True)
            self._prune_spool()
            return
        self._prune_spool()
        # Sobe o frame recém-capturado primeiro; depois drena backlog antigo.
        if self._upload_frame(frame_path):
            self._drain_backlog()

    def _queue_event_frame(self, data: bytes, event_id: str, state: str) -> None:
        """Acumula um frame do evento; faz flush a cada EVENT_BATCH_SIZE frames
        OU imediatamente quando o evento fecha (state end/end_transient)."""
        # Troca de evento sem ter fechado o anterior: fecha o lote pendente.
        if self._event_batch and self._event_batch[0][1] != event_id:
            self._flush_event_batch()
        self._event_batch.append((data, event_id, state))
        if (
            state in ("end", "end_transient")
            or len(self._event_batch) >= self._event_batch_size
        ):
            self._flush_event_batch()

    def _flush_event_batch(self) -> None:
        """Sobe o lote acumulado num único POST /upload-batch. Em falha, cai
        para o spool por frame (preserva resiliência e o manifest)."""
        if not self._event_batch:
            return
        batch = self._event_batch
        self._event_batch = []
        event_id = batch[0][1]
        # Estado do lote: fecha o manifest só se o último frame for terminal.
        last_state = batch[-1][2]
        batch_state = last_state if last_state in ("end", "end_transient") else "active"
        files = [
            ("imageFile", (f"f{i:03d}.jpg", d, "image/jpeg"))
            for i, (d, _eid, _st) in enumerate(batch)
        ]
        form = {"event_id": event_id, "event_state": batch_state}
        # Anexa os stats do gate (server faz first-non-null-wins). Libera no fim.
        form.update(self._gate_stats_pending.get(event_id, {}))
        if batch_state in ("end", "end_transient"):
            self._gate_stats_pending.pop(event_id, None)
        try:
            resp = self._ec2_session.post(
                self.cfg.batch_upload_url, files=files, data=form,
                timeout=self.cfg.upload_timeout_s * 2,
            )
        except requests.RequestException as exc:
            log.warning(
                "Batch upload falhou (%d frames, %s): %s — caindo p/ spool",
                len(batch), event_id, exc,
            )
            for d, eid, st in batch:
                self._spool_and_upload(d, event_id=eid, event_state=st)
            return
        if resp.status_code == 200:
            self._last_upload_at = time.time()
            log.info("Batch OK %s: %d frames (state=%s)", event_id, len(batch), batch_state)
        else:
            log.warning(
                "Batch HTTP %s (%s) — caindo p/ spool", resp.status_code, event_id
            )
            for d, eid, st in batch:
                self._spool_and_upload(d, event_id=eid, event_state=st)

    def _upload_frame(self, frame_path: Path) -> bool:
        try:
            data = frame_path.read_bytes()
        except OSError:
            return False
        # Frame corrompido (escrita parcial / disco cheio): descarta em vez de
        # subir lixo. Não marca .uploaded (some do backlog ao apagar).
        if len(data) < 500 or data[:2] != b"\xff\xd8":
            log.warning("Frame corrompido no spool (%s, %d bytes) — descartado",
                        frame_path.name, len(data))
            frame_path.unlink(missing_ok=True)
            frame_path.with_name(frame_path.name + UPLOADED_SUFFIX).unlink(missing_ok=True)
            return False
        files = {"imageFile": ("snapshot.jpg", data, "image/jpeg")}
        event_id, event_state = self._parse_spool_name(frame_path.name)
        form = {}
        if event_id:
            form = {"event_id": event_id, "event_state": event_state}
            # Fallback (spool por-frame): anexa os stats do gate ao evento.
            form.update(self._gate_stats_pending.get(event_id, {}))
            if event_state in ("end", "end_transient"):
                self._gate_stats_pending.pop(event_id, None)
        t0 = time.monotonic()
        try:
            resp = self._ec2_session.post(
                self.cfg.upload_url, files=files, data=form,
                timeout=self.cfg.upload_timeout_s,
            )
        except requests.RequestException as exc:
            log.warning("Upload falhou (%s): %s — frame fica no spool", frame_path.name, exc)
            return False
        if resp.status_code == 200:
            frame_path.with_name(frame_path.name + UPLOADED_SUFFIX).touch()
            self._last_upload_at = time.time()
            log.info("Upload OK %s (%d bytes, %dms, backlog=%d)", frame_path.name,
                     len(data), int((time.monotonic() - t0) * 1000),
                     len(self._pending_frames()))
            return True
        log.warning("Upload HTTP %s (%s)", resp.status_code, frame_path.name)
        return False

    def _post_keepalive(self) -> bool:
        """Keepalive + telemetria de saúde no corpo JSON. O servidor faz touch
        no marcador (offline_monitor mantém a câmera 'online') e grava
        .health.json. Retrocompatível: servidor antigo ignora o corpo. ~1KB."""
        try:
            resp = self._ec2_session.post(
                self.cfg.keepalive_url, json=self._health_snapshot(), timeout=10,
            )
            if resp.status_code == 200:
                self._last_upload_at = time.time()  # reusa o relógio do heartbeat
                return True
            log.debug("Keepalive HTTP %s", resp.status_code)
        except requests.RequestException as exc:
            log.debug("Keepalive falhou: %s", exc)
        return False

    # ----- telemetria / saúde --------------------------------------------
    def telemetry_loop(self) -> None:
        """Emite keepalive + telemetria a cada heartbeat, INDEPENDENTE da
        captura — a Pi continua 'online' e reporta mesmo com a câmera caída
        (camera_ok=false), distinguindo 'Pi muda' de 'câmera offline'."""
        while not self._stop.is_set():
            self._beat("telemetry")
            try:
                self._disk_guard()
                self._refresh_zoom_cached()
                self._post_keepalive()
            except Exception:  # noqa: BLE001
                log.exception("Falha no ciclo de telemetria")
            self._stop.wait(max(10.0, float(self._heartbeat_interval)))

    def _clips_stats(self) -> tuple[Optional[int], Optional[int]]:
        """(quantidade, MB) dos clipes confirmados no SD — visibilidade do
        orçamento da cadeia na telemetria."""
        try:
            sizes = [f.stat().st_size for f in self.cfg.clips_dir.glob("*.mp4")]
        except OSError:
            return None, None
        return len(sizes), int(sum(sizes) / (1024 * 1024))

    def _health_snapshot(self) -> dict:
        now = time.time()
        clips_count, clips_mb = self._clips_stats()
        cam_age = (now - self._last_capture_ok_at) if self._last_capture_ok_at else None
        camera_ok = cam_age is not None and cam_age < max(30.0, 2 * self._heartbeat_interval)
        up_age = (now - self._last_upload_at) if self._last_upload_at else None
        evt_age = (now - self._last_event_at) if self._last_event_at else None
        return {
            "device_id": self.cfg.device_id,
            "agent_version": self.cfg.agent_version,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "uptime_s": int(time.monotonic() - self._start_monotonic),
            "clock_synced": self._clock_synced(),
            "motion_mode": self._motion_mode,
            "safe_mode": self._safe_mode,
            "live_active": self._live_active(now),
            # RELATIVO, nunca o epoch absoluto do deadline: o relógio da Pi
            # derrapa (é por isso que este mesmo health reporta clock_synced), e
            # um epoch cru viraria ruído indebugável no painel.
            "live_remaining_s": round(max(0.0, self._live_until - now), 1)
            if self._live_active(now)
            else None,
            "gate_state": self._gate.state if self._gate is not None else "off",
            "config_version": self._config_version,
            "rejected_config_keys": sorted(self._rejected_config.keys()),
            "log_level": self._log_level,
            "snapshot_source": self._snapshot_source,
            "heartbeat_mode": self._heartbeat_mode,
            "last_capture_source": self._last_capture_source,
            "last_capture_age_s": round(cam_age, 1) if cam_age is not None else None,
            "camera_ok": camera_ok,
            # Posição atual da lente motorizada (0=aberto, 1=tele); None se não
            # lida / câmera sem zoom óptico. Alimenta o "Zoom atual" no painel.
            "zoom": self._last_zoom,
            "rtsp_buffer_ok": self._rtsp_buffer_ok(),
            # Breaker do fallback HTTP ABERTO agora = a porta 80 está em cooldown
            # (morta/flapando); o RTSP segura a captura. Usa o relógio do breaker
            # (monotonic) e volta a False sozinho ao fim do cooldown — não fica
            # preso em True após o episódio.
            "http_fallback_breaker": time.monotonic() < self._http_breaker_until,
            "last_upload_age_s": round(up_age, 1) if up_age is not None else None,
            "last_event_id": self._last_event_id,
            "last_event_age_s": round(evt_age, 1) if evt_age is not None else None,
            "events_today": self._events_today,
            "fg_px": self._last_fg_px,
            "delta_px": self._last_delta_px,
            "spool_depth": self._spool_depth(),
            "backlog_depth": len(self._pending_frames()),
            "clips_count": clips_count,
            "clips_mb": clips_mb,
            "disk_free_mb": self._disk_free_mb(self.cfg.clips_dir),
            "spool_free_mb": self._disk_free_mb(self.cfg.spool_dir),
            "disk_low": self._disk_low,
            "cpu_temp_c": self._cpu_temp_c(),
            "throttled": self._throttled(),
            "load_avg": self._load_avg(),
            "mem_free_mb": self._mem_free_mb(),
        }

    def _spool_depth(self) -> int:
        try:
            return sum(1 for _ in self.cfg.spool_dir.glob("*.jpg"))
        except OSError:
            return -1

    @staticmethod
    def _disk_free_mb(path: Path) -> Optional[int]:
        try:
            return int(shutil.disk_usage(path).free // (1024 * 1024))
        except OSError:
            return None

    def _rtsp_buffer_ok(self) -> Optional[bool]:
        try:
            age = time.time() - self.cfg.snapshot_jpg.stat().st_mtime
        except OSError:
            return None
        return age < max(10.0, self.cfg.snapshot_max_age_s * 2)

    @staticmethod
    def _clock_synced() -> Optional[bool]:
        try:
            return Path("/run/systemd/timesync/synchronized").exists()
        except OSError:
            return None

    @staticmethod
    def _cpu_temp_c() -> Optional[float]:
        try:
            raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
            return round(int(raw) / 1000.0, 1)
        except (OSError, ValueError):
            return None

    @staticmethod
    def _throttled() -> Optional[str]:
        try:
            out = subprocess.run(
                ["vcgencmd", "get_throttled"], capture_output=True, timeout=5, text=True,
            )
            val = out.stdout.strip()
            return val.split("=", 1)[1] if "=" in val else (val or None)
        except (OSError, subprocess.SubprocessError):
            return None

    @staticmethod
    def _load_avg() -> Optional[float]:
        try:
            return round(os.getloadavg()[0], 2)
        except (OSError, AttributeError):
            return None

    @staticmethod
    def _mem_free_mb() -> Optional[int]:
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
        except (OSError, ValueError, IndexError):
            pass
        return None

    def _disk_guard(self) -> None:
        """Se o espaço cair abaixo do piso, poda agressivamente e alerta uma
        vez (best-effort; nunca derruba a thread)."""
        free = self._disk_free_mb(self.cfg.clips_dir)
        spool_free = self._disk_free_mb(self.cfg.spool_dir)
        floor = self.cfg.min_disk_free_mb
        low = (free is not None and free < floor) or (
            spool_free is not None and spool_free < floor
        )
        if low and not self._disk_low:
            log.warning("Disco baixo (clips=%sMB spool=%sMB < %dMB) — poda agressiva",
                        free, spool_free, floor)
            self._post_status(f"disk_low clips={free}MB spool={spool_free}MB")
        if low:
            self._emergency_prune()
        self._disk_low = low

    def _emergency_prune(self) -> None:
        try:
            clips = sorted(self.cfg.clips_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
            for old in clips[:-3]:  # mantém os 3 clipes mais novos
                old.unlink(missing_ok=True)
                log.info("Disco baixo: clipe %s removido", old.name)
        except OSError:
            pass
        try:
            frames = sorted(self.cfg.spool_dir.glob("*.jpg"), reverse=True)
            for old in frames[max(5, self.cfg.keep_frames // 2):]:
                old.unlink(missing_ok=True)
                old.with_name(old.name + UPLOADED_SUFFIX).unlink(missing_ok=True)
        except OSError:
            pass

    # ----- watchdog ------------------------------------------------------
    def _thread_limits(self) -> dict[str, float]:
        return {
            "capture": self.cfg.watchdog_capture_stall_s,
            "config": max(0.0, self.cfg.config_poll_interval_s * 3.0),
            # +1200s de folga: um dispatch pode conter export (ffmpeg ≤120s) +
            # upload de cadeia costurada (timeout ≤900s) — operações BOUNDED.
            # O watchdog continua pegando hang de verdade, só que com teto
            # de ~21 min na thread de comando.
            "command": max(0.0, self.cfg.command_poll_timeout_s * 3.0 + 30.0 + 1200.0),
            "telemetry": max(0.0, self._heartbeat_interval * 3.0 + 30.0),
        }

    def _watchdog_overdue(self, mono: float, wall: float) -> Optional[str]:
        """Função pura: devolve o motivo (nome da thread ou 'mute') se algo
        estourou o limiar, senão None. Separado do loop para ser testável."""
        for name, limit in self._thread_limits().items():
            if limit <= 0:
                continue
            if mono - self._beats.get(name, mono) > limit:
                return f"thread:{name}"
        mute = self.cfg.watchdog_mute_restart_s
        if mute > 0 and self._last_upload_at > 0 and (wall - self._last_upload_at) > mute:
            return "mute"
        return None

    def watchdog_loop(self) -> None:
        """Reinicia o processo (os._exit -> systemd) se uma thread travar
        ('vivo mas mudo') e bate o WatchdogSec do systemd a cada tick."""
        while not self._stop.is_set():
            try:
                sd_notify("WATCHDOG=1")
                reason = self._watchdog_overdue(time.monotonic(), time.time())
                if reason is not None:
                    log.critical("Watchdog: %s estourou o limiar — reiniciando processo", reason)
                    self._die()
            except Exception:  # noqa: BLE001 - watchdog jamais pode morrer
                log.exception("Erro no watchdog (ignorado)")
            self._stop.wait(self.cfg.watchdog_tick_s)

    @staticmethod
    def _die() -> None:
        logging.shutdown()
        os._exit(1)

    def _fresh_local_snapshot(self) -> bytes | None:
        """latest.jpg do RTSP se estiver FRESCO (mtime ≤ snapshot_max_age_s) e for
        JPEG válido; senão None. O guard de idade é essencial: sem ele, um
        cam-rtsp-buffer travado faz o leitor reenviar o mesmo frame congelado
        indefinidamente — o painel "ao vivo" fica preso numa cena velha. Com o
        guard, quando o buffer para, o chamador cai para o snapshot HTTP (a câmera
        em geral ainda responde por HTTP mesmo com o RTSP fora)."""
        path = self.cfg.snapshot_jpg
        try:
            if time.time() - path.stat().st_mtime > self.cfg.snapshot_max_age_s:
                return None
            raw = path.read_bytes()
        except OSError:
            return None
        if len(raw) >= 500 and raw[:2] == b"\xff\xd8":
            return raw
        return None

    def _upload_snapshot_now(self) -> None:
        """CMD_SNAPSHOT: sobe UM frame atual sob demanda (abrir painel / "atualizar
        agora"). Sem event_id → vira a "última imagem" do painel, não dispara o
        worker. Prefere o latest.jpg do RTSP se estiver fresco; se o buffer travou
        (frame velho), cai para o snapshot HTTP para não servir cena congelada."""
        data = self._fresh_local_snapshot() or self._fetch_snapshot_http()
        if data:
            self._spool_and_upload(data)
            log.info("CMD_SNAPSHOT: frame enviado (%d bytes)", len(data))
        else:
            log.warning("CMD_SNAPSHOT: sem frame disponível")

    # ----- controle de zoom (lente motorizada Intelbras/Dahua) -----------
    def _camera_base(self) -> str:
        """http://host[:porta] extraído do IP_CAM_URL (a câmera só é alcançável
        de dentro da LAN da Pi)."""
        from urllib.parse import urlparse
        with self._lock:
            u = urlparse(self._cam_url)
        return f"{u.scheme or 'http'}://{u.netloc}"

    def _devvideo(self, action: str, **params):
        with self._lock:
            user, pwd = self._cam_user, self._cam_pass
        return self._cam_session.get(
            f"{self._camera_base()}/cgi-bin/devVideoInput.cgi",
            params={"action": action, "channel": 0, **params},
            auth=HTTPDigestAuth(user, pwd),
            timeout=self.cfg.cam_timeout_s,
        )

    def _read_zoom(self) -> float | None:
        try:
            for line in self._devvideo("getFocusStatus").text.splitlines():
                k, _, v = line.partition("=")
                if k.strip().lower().endswith(".zoom"):
                    return float(v.strip())
        except (requests.RequestException, ValueError):
            pass
        return None

    def _refresh_zoom_cached(self) -> None:
        """Relê o zoom da câmera para a telemetria, no MÁXIMO 1×/ZOOM_REFRESH_S.
        Chamado no ciclo de telemetria. Só um GET espaçado (nunca rajada) — o
        httpd da câmera colapsa sob rajada. A janela vale mesmo quando a leitura
        falha (câmera fora), pra não martelar getFocusStatus a cada heartbeat;
        uma leitura None mantém o último zoom conhecido."""
        now = time.monotonic()
        if self._last_zoom_read_at > 0 and (now - self._last_zoom_read_at) < ZOOM_REFRESH_S:
            return
        z = self._read_zoom()
        self._last_zoom_read_at = now
        if z is not None:
            self._last_zoom = z

    def _handle_zoom_cmd(self, arg: str) -> None:
        """CMD_ZOOM:<0-1> — zoom óptico absoluto (0=aberto, 1=tele). Reenvia o
        adjustFocus até convergir (a lente ignora comando durante autofoco),
        roda autofoco e sobe um frame pro painel refletir o novo enquadramento."""
        try:
            target = max(0.0, min(1.0, float(arg)))
        except ValueError:
            log.warning("CMD_ZOOM arg inválido: %s", arg)
            return
        try:
            for _ in range(8):
                self._devvideo("adjustFocus", zoom=f"{target:.4f}", focus=f"{target:.4f}")
                time.sleep(1.5)
                z = self._read_zoom()
                if z is not None and abs(z - target) <= 0.03:
                    break
            self._devvideo("autoFocus")
        except requests.RequestException as exc:
            log.warning("CMD_ZOOM falhou: %s", exc)
            return
        applied = self._read_zoom()
        if applied is not None:  # atualiza o cache da telemetria de graça
            self._last_zoom = applied
            self._last_zoom_read_at = time.monotonic()
        log.info("CMD_ZOOM: zoom=%.2f aplicado (lido=%s)", target, applied)
        # Enquadramento mudou -> baseline do gate inválido: re-anchor.
        self._recalibrate_requested = True
        self._upload_snapshot_now()

    def _handle_autofocus_cmd(self) -> None:
        try:
            self._devvideo("autoFocus")
            log.info("CMD_AUTOFOCUS aplicado")
        except requests.RequestException as exc:
            log.warning("CMD_AUTOFOCUS falhou: %s", exc)
            return
        self._upload_snapshot_now()

    # ----- logs remotos --------------------------------------------------
    def _read_recent_logs(self, n: int) -> str:
        """Últimas N linhas do log rotativo; cai para journalctl se sem arquivo."""
        try:
            if self.cfg.log_file.is_file():
                lines = self.cfg.log_file.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                return "\n".join(lines[-n:])
        except OSError:
            pass
        try:
            out = subprocess.run(
                ["journalctl", "-u", "saira-agent", "-n", str(n), "--no-pager"],
                capture_output=True, timeout=30, text=True,
            )
            return out.stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    def _send_logs(self, arg: str) -> None:
        """CMD_GET_LOGS[:n] — sobe as últimas N linhas do log (default 500) para
        POST /device/<id>/logs. Permite rastrear o teste de campo sem SSH."""
        try:
            n = max(1, min(5000, int(arg))) if arg else 500
        except ValueError:
            n = 500
        text = self._read_recent_logs(n)
        if not text:
            log.warning("CMD_GET_LOGS: sem log disponível")
            self._post_status("logs_unavailable")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"{self.cfg.device_id}_{ts}.log"
        try:
            resp = self._ec2_session.post(
                self.cfg.logs_url,
                files={"logFile": (fname, text.encode("utf-8", "replace"), "text/plain")},
                timeout=self.cfg.upload_timeout_s * 2,
            )
            log.info("CMD_GET_LOGS: %d linhas enviadas HTTP %s", n, resp.status_code)
        except requests.RequestException as exc:
            log.warning("CMD_GET_LOGS upload falhou: %s", exc)

    # ----- modo calibração ----------------------------------------------
    def _fetch_calib_frame(self) -> Optional[bytes]:
        """Frame para calibração: latest.jpg do RTSP se fresco, caindo p/ snapshot
        HTTP (mesmo guard de idade do CMD_SNAPSHOT — evita calibrar sobre um frame
        congelado por buffer travado)."""
        return self._fresh_local_snapshot() or self._fetch_snapshot_http()

    def _run_calibration(self, arg: str) -> None:
        """CMD_CALIBRATE[:s] — por S segundos mede fg/delta com uma sonda
        independente do gate vivo e sobe (1) um snapshot ANOTADO (polígono +
        heatmap de foreground + painel) para /upload e (2) um relatório JSON
        para /device/<id>/logs. Modo calibração remoto: desenhar a zona e achar
        o enquadramento sem ir ao local."""
        # Default 60s (era 20): a 1 Hz, 20s deixava só 10 amostras depois do
        # descarte de convergência — p95 de 10 amostras é o próprio max.
        try:
            secs = max(3, min(120, int(arg))) if arg else 60
        except ValueError:
            secs = 60
        log.info("CMD_CALIBRATE: amostrando por %ds", secs)
        polygon = self._last_good_polygon
        try:
            from motion_gate import CalibrationProbe
        except ImportError as exc:
            log.warning("CMD_CALIBRATE: cv2/numpy indisponíveis (%s) — só snapshot cru", exc)
            self._upload_snapshot_now()
            self._post_status(f"calibrate framing-only (sem cv2: {exc})")
            return
        probe = CalibrationProbe(
            polygon_json=polygon,
            history=self.cfg.pi_bgsub_history,
            var_threshold=self.cfg.pi_bgsub_var_threshold,
            shadow_threshold=self.cfg.pi_bgsub_shadow_threshold,
        )
        samples: list[tuple[int, int]] = []
        last_frame: Optional[bytes] = None
        deadline = time.monotonic() + secs
        while time.monotonic() < deadline and not self._stop.is_set():
            frame = self._fetch_calib_frame()
            if frame is not None:
                last_frame = frame
                m = probe.measure(frame)
                if m is not None:
                    samples.append(m)
            self._stop.wait(1.0)

        if not samples or last_frame is None:
            log.warning("CMD_CALIBRATE: sem frames")
            self._post_status("calibrate no-frames")
            return

        # O MOG2 da sonda nasce vazio: no 1º frame a zona INTEIRA é foreground
        # (medido: fg_px=62275 = 100% da zona, e 0 no frame seguinte). Descartar
        # a convergência é obrigatório — sem isso o max() herda esse outlier e a
        # sugestão vira maior que a própria zona (bug de campo: 93462).
        # Janela curta demais para descartar a convergência: ainda reportamos a
        # distribuição medida, mas NÃO sugerimos threshold — um número
        # contaminado pelo cold-start é pior que nenhum (foi assim que nasceu o
        # 93462, maior que a própria zona).
        settled_ok = len(samples) > _CALIB_SETTLE_FRAMES
        settled = samples[_CALIB_SETTLE_FRAMES:] if settled_ok else samples
        discarded = _CALIB_SETTLE_FRAMES if settled_ok else 0

        fgs = [s[0] for s in settled]
        deltas = [s[1] for s in settled]
        cur_min_active = self._gate.min_px_active if self._gate else self.cfg.pi_bgsub_min_px_active
        cur_delta_start = self._gate.delta_start_px if self._gate else self.cfg.pi_bgsub_delta_start_px

        def _stats(vals: list[int]) -> dict:
            return {
                "min": min(vals), "max": max(vals),
                "mean": round(sum(vals) / len(vals), 1),
                "p50": _percentile(vals, 0.50),
                "p95": _percentile(vals, 0.95),
                "p99": _percentile(vals, 0.99),
            }

        fg_stats, delta_stats = _stats(fgs), _stats(deltas)
        report = {
            "device_id": self.cfg.device_id,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "seconds": secs,
            "frames": len(settled),
            "frames_discarded": discarded,
            "fg_px": fg_stats,
            "delta_px": delta_stats,
            "current": {
                "pile_zone_polygon": polygon,
                "min_px_active": cur_min_active,
                "delta_start_px": cur_delta_start,
            },
            # Piso acima do ruído observado (folga 1,5×+50) sobre o p95, não o
            # max: uma única passagem de carro/farol durante a janela não pode
            # ditar o threshold.
            "suggested": {
                "min_px_active": int(fg_stats["p95"] * 1.5) + 50,
                "delta_start_px": int(delta_stats["p95"] * 1.5) + 50,
            } if settled_ok else None,
            "suggestion_basis": (
                f"p95 ×1,5 +50, após descartar {discarded} frames de "
                f"convergência do MOG2"
            ) if settled_ok else (
                f"sem sugestão: {len(samples)} frames não bastam para descartar "
                f"os {_CALIB_SETTLE_FRAMES} de convergência do MOG2 — "
                f"repita com uma janela maior"
            ),
            # A janela é curta por construção (bloqueia a thread de comandos).
            # Sem este aviso o operador lê a sugestão como verdade do dia todo —
            # foi o que aconteceu em 14/07: uma janela noturna curta sugeriu 8×
            # de folga, e a madrugada real chegou a 28× o medido.
            "horizon_warning": (
                f"janela de {secs}s num único instante: NÃO cobre variação de "
                f"iluminação (farol, amanhecer, chuva). Para thresholds de "
                f"produção, medir ao menos 1 noite inteira."
            ),
        }
        last_fg, last_delta = samples[-1]
        # ASCII de propósito: o painel é desenhado com cv2.putText (fonte
        # Hershey), que não tem glifo para acento — "NÃO" sairia "N??O".
        # O relatório JSON acima leva o texto acentuado de verdade.
        lines = [
            f"CALIB {self.cfg.device_id} {report['ts']}",
            f"fg_px now={last_fg} p50={fg_stats['p50']} p95={fg_stats['p95']} max={fg_stats['max']}",
            f"delta_px now={last_delta} p50={delta_stats['p50']} p95={delta_stats['p95']} max={delta_stats['max']}",
            f"atual: min_px_active={cur_min_active} delta_start_px={cur_delta_start}",
            (
                f"sugerido: min_px_active>={report['suggested']['min_px_active']} "
                f"delta_start_px>={report['suggested']['delta_start_px']}"
                if settled_ok
                else f"sem sugestao: janela curta demais ({len(samples)} frames)"
            ),
            f"({len(settled)} frames, {discarded} descartados; "
            f"janela {secs}s NAO cobre a noite)",
        ]
        annotated = probe.annotate(last_frame, lines)
        self._spool_and_upload(annotated if annotated else last_frame)
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._ec2_session.post(
                self.cfg.logs_url,
                files={"logFile": (f"calib_{self.cfg.device_id}_{ts}.json",
                                   json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8"),
                                   "application/json")},
                timeout=self.cfg.upload_timeout_s * 2,
            )
        except requests.RequestException as exc:
            log.warning("CMD_CALIBRATE: upload do relatório falhou: %s", exc)
        log.info("CMD_CALIBRATE: %d frames, fg[%d..%d] delta[%d..%d]",
                 len(samples), min(fgs), max(fgs), min(deltas), max(deltas))

    def _pending_frames(self) -> list[Path]:
        frames = sorted(self.cfg.spool_dir.glob("*.jpg"), reverse=True)  # mais novo primeiro
        return [f for f in frames if not f.with_name(f.name + UPLOADED_SUFFIX).exists()]

    def _drain_backlog(self) -> None:
        for frame in self._pending_frames()[: self.cfg.backlog_per_cycle]:
            if self._stop.is_set() or not self._upload_frame(frame):
                break

    def _prune_spool(self) -> None:
        frames = sorted(self.cfg.spool_dir.glob("*.jpg"), reverse=True)
        for old in frames[self.cfg.keep_frames:]:
            old.unlink(missing_ok=True)
            old.with_name(old.name + UPLOADED_SUFFIX).unlink(missing_ok=True)

    # ----- config remota -------------------------------------------------
    def config_loop(self) -> None:
        etag: str | None = None
        while not self._stop.is_set():
            self._beat("config")
            try:
                headers = {"If-None-Match": etag} if etag else {}
                resp = self._ec2_session.get(
                    self.cfg.config_url, headers=headers, timeout=15
                )
                if resp.status_code == 200:
                    etag = resp.headers.get("ETag", etag)
                    self._apply_config(resp.text)
            except requests.RequestException as exc:
                log.debug("Config poll falhou: %s", exc)
            self._stop.wait(self.cfg.config_poll_interval_s)

    @staticmethod
    def _as_bool(s: str) -> bool:
        return s.strip().lower() not in ("0", "false", "no", "off", "")

    @staticmethod
    def _validate_polygon(polygon_json: str) -> bool:
        """True se o JSON parseia e tem ≥1 polígono não-degenerado (≥3 pontos,
        área ≥0,2% do frame de referência, pontos dentro dos limites). Puro
        Python (sem cv2): roda mesmo com o gate desligado. Vazio = frame inteiro
        (válido). Impede que um polígono minúsculo/zerado cegue a detecção."""
        s = (polygon_json or "").strip()
        if not s:
            return True
        try:
            raw = json.loads(s)
            if raw and isinstance(raw[0][0], (int, float)):
                raw = [raw]
            min_area = 0.002 * POLYGON_REF_W * POLYGON_REF_H
            for poly in raw:
                if len(poly) < 3:
                    continue
                if any(
                    not (-1 <= x <= POLYGON_REF_W + 1 and -1 <= y <= POLYGON_REF_H + 1)
                    for x, y in poly
                ):
                    continue
                n = len(poly)
                area = abs(sum(
                    poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1]
                    for i in range(n)
                )) / 2.0
                if area >= min_area:
                    return True
            return False
        except (ValueError, TypeError, IndexError, KeyError):
            return False

    def _apply_config(self, body: str) -> None:
        """Aplica config remota com validação + rejeição visível + rollback
        leve (mantém valor anterior) + kill-switch safe_mode. Chaves inválidas
        NÃO são engolidas em silêncio: vão para self._rejected_config e a
        telemetria, e o operador vê o que de fato está vivo."""
        kv: dict[str, str] = {}
        for line in body.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
        rej: dict[str, str] = {}

        if "version" in kv and kv["version"]:
            self._config_version = kv["version"]

        # log_level: hot-reload, sempre aplicável (mesmo em safe_mode).
        if "log_level" in kv:
            lvl = kv["log_level"].strip().upper()
            if lvl in _LOG_LEVELS:
                if lvl != self._log_level:
                    logging.getLogger().setLevel(lvl)
                    self._log_level = lvl
                    log.info("Config: log_level -> %s", lvl)
            else:
                rej["log_level"] = kv["log_level"]

        # safe_mode: kill-switch. Liga -> força estado seguro (frames fluindo).
        safe = self._safe_mode
        if "safe_mode" in kv:
            safe = self._as_bool(kv["safe_mode"])

        with self._lock:
            was_safe = self._safe_mode
            self._safe_mode = safe
            if safe:
                if not was_safe:
                    log.warning("Config: SAFE_MODE LIGADO — motion=off, intervalo "
                                "padrão, heartbeat=image (escape garantido)")
                self._motion_mode = "off"
                self._heartbeat_mode = "image"
                self._interval = max(MIN_CAPTURE_INTERVAL_S, self.cfg.capture_interval_s)
            else:
                if was_safe:
                    log.info("Config: SAFE_MODE DESLIGADO")
                self._apply_runtime_keys(kv, rej)

        if not safe:
            self._apply_gate_keys(kv, rej)

        self._rejected_config = rej
        if rej:
            log.warning("Config v%s: chaves REJEITADAS (mantido valor anterior): %s",
                        self._config_version,
                        ", ".join(f"{k}={v!r}" for k, v in rej.items()))

    def _apply_runtime_keys(self, kv: dict, rej: dict) -> None:
        """Chaves de runtime do agente (chamado sob self._lock, fora do safe_mode).
        Cadências CLAMPAM em [piso,teto]; thresholds/tamanhos REJEITAM fora da faixa."""
        if "timer_delay_ms" in kv:
            v = _cfg_clamp(kv, rej, "timer_delay_ms", MIN_CAPTURE_INTERVAL_S, 3600.0, int, 0.001)
            if v is not None and v != self._interval:
                log.info("Config: intervalo %.1fs -> %.1fs", self._interval, v)
                self._interval = v

        for key, attr in (("ip_cam_url", "_cam_url"), ("ip_cam_user", "_cam_user"),
                          ("ip_cam_pass", "_cam_pass")):
            if key in kv and getattr(self, attr) != kv[key]:
                log.info("Config: %s atualizado", key)
                setattr(self, attr, kv[key])
                if key == "ip_cam_url":
                    # Câmera/posição pode ter mudado -> baseline inválido.
                    self._recalibrate_requested = True

        if "burst_interval_ms" in kv:
            v = _cfg_clamp(kv, rej, "burst_interval_ms", 0.5, 60.0, int, 0.001)
            if v is not None:
                self._burst_interval = v
        if "idle_analyze_interval_ms" in kv:
            v = _cfg_clamp(kv, rej, "idle_analyze_interval_ms", MIN_ANALYZE_INTERVAL_S, 600.0, int, 0.001)
            if v is not None:
                self._idle_analyze_interval = v
        if "heartbeat_interval_ms" in kv:
            v = _cfg_clamp(kv, rej, "heartbeat_interval_ms", 10.0, 3600.0, int, 0.001)
            if v is not None:
                self._heartbeat_interval = v
        if "live_interval_ms" in kv:
            # Piso de 0,5s é teórico: o latest.jpg só muda por keyframe (~1-2s),
            # então pedir menos não traz frame novo — só gasta CPU no stat().
            v = _cfg_clamp(kv, rej, "live_interval_ms", 0.5, 10.0, int, 0.001)
            if v is not None:
                self._live_interval = v
        if "event_min_residual_px" in kv:
            v = _cfg_num(kv, rej, "event_min_residual_px", 0, 1_000_000, int)
            if v is not None:
                self._event_min_residual_px = v
        if "event_batch_size" in kv:
            v = _cfg_num(kv, rej, "event_batch_size", 0, 64, int)
            if v is not None:
                self._event_batch_size = v
        if "motion_send_pre_frame" in kv:
            self._send_pre_frame = self._as_bool(kv["motion_send_pre_frame"])
        # Cadeia de clipes (atributos do ClipStore: escrita atômica de
        # int/bool sob o GIL, mesmo padrão dos knobs do gate).
        if "clip_chain_enabled" in kv:
            self._clips.chain_enabled = self._as_bool(kv["clip_chain_enabled"])
        if "clip_chain_gap_s" in kv:
            v = _cfg_num(kv, rej, "clip_chain_gap_s", 0, 3600, int)
            if v is not None:
                self._clips.chain_gap_s = v
        if "clip_chain_span_s" in kv:
            v = _cfg_num(kv, rej, "clip_chain_span_s", 0, 7200, int)
            if v is not None:
                self._clips.chain_span_s = v
        if "clip_chain_max_s" in kv:
            v = _cfg_num(kv, rej, "clip_chain_max_s", 60, 3600, int)
            if v is not None:
                self._clips.chain_max_s = v
        if "clips_max_mb" in kv:
            v = _cfg_num(kv, rej, "clips_max_mb", 512, 65536, int)
            if v is not None:
                self._clips.clips_max_bytes = v * 1024 * 1024
        if "snapshot_source" in kv:
            src = kv["snapshot_source"].strip().lower()
            if src in ("auto", "rtsp", "http"):
                self._snapshot_source = src
            else:
                rej["snapshot_source"] = kv["snapshot_source"]
        if "heartbeat_mode" in kv:
            hm = kv["heartbeat_mode"].strip().lower()
            if hm in ("image", "keepalive"):
                self._heartbeat_mode = hm
            else:
                rej["heartbeat_mode"] = kv["heartbeat_mode"]
        if "motion_enabled" in kv:
            new_mode = kv["motion_enabled"].strip().lower()
            if new_mode not in ("off", "shadow", "on"):
                rej["motion_enabled"] = kv["motion_enabled"]
            elif new_mode != self._motion_mode:
                if new_mode != "off" and self._gate is None:
                    self._gate = self._build_gate()
                if new_mode == "off" or self._gate is not None:
                    log.info("Config: motion %s -> %s", self._motion_mode, new_mode)
                    self._motion_mode = new_mode

    def _apply_gate_keys(self, kv: dict, rej: dict) -> None:
        """Tuning do gate (fora do lock; gate é da thread de captura, mas são
        escritas atômicas de int). Com clamps e guard de polígono."""
        if self._gate is None:
            return
        if "pile_zone_polygon" in kv:
            if self._validate_polygon(kv["pile_zone_polygon"]):
                self._gate.set_polygon(kv["pile_zone_polygon"])
                self._last_good_polygon = kv["pile_zone_polygon"]
            else:
                rej["pile_zone_polygon"] = (kv["pile_zone_polygon"][:40] + "…") \
                    if len(kv["pile_zone_polygon"]) > 40 else kv["pile_zone_polygon"]
                log.warning("Config: pile_zone_polygon degenerado — mantido o anterior")
        for key, attr, lo, hi in (
            ("motion_min_px_active", "min_px_active", 10, 1_000_000),
            ("motion_delta_start_px", "delta_start_px", 10, 1_000_000),
            ("motion_warmup_s", "warmup_seconds", 10, 3600),
            ("event_max_s", "event_max_s", 30, 3600),
            ("event_end_quiet_s", "event_end_quiet_s", 3, 3600),
        ):
            if key not in kv:
                continue
            try:
                val = int(kv[key])
            except (ValueError, TypeError):
                rej[key] = kv[key]
                continue
            if val < lo or val > hi:
                rej[key] = kv[key]
                continue
            setattr(self._gate, attr, val)
            if key == "event_max_s":
                # A estimativa de adjacência da cadeia acompanha o gate vivo.
                self._clips.event_max_s = val

    # ----- comandos sob demanda -----------------------------------------
    def command_loop(self) -> None:
        while not self._stop.is_set():
            self._beat("command")
            try:
                resp = self._ec2_session.get(
                    self.cfg.poll_url,
                    params={"timeout": self.cfg.command_poll_timeout_s},
                    timeout=self.cfg.command_poll_timeout_s + 10,
                )
                cmd = (resp.json() or {}).get("cmd") if resp.status_code == 200 else None
            except (requests.RequestException, ValueError) as exc:
                log.debug("Command poll falhou: %s", exc)
                self._stop.wait(3.0)
                continue
            if not cmd:
                continue
            log.info("Comando recebido: %s", cmd)
            name, _, arg = str(cmd).partition(":")
            arg = arg.strip()
            t0 = time.monotonic()
            try:
                self._dispatch_command(name, arg, cmd)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao executar comando %s", cmd)
            else:
                log.info("Comando %s concluído (%dms)", name,
                         int((time.monotonic() - t0) * 1000))

    def _dispatch_command(self, name: str, arg: str, cmd: str) -> None:
        if name == "CMD_VIDEO_CLIP" and arg:
            self._upload_event_clip(arg)
        elif name == "CMD_VIDEO_CLIP":
            self._export_and_upload_ring()
        elif name == "CMD_PERSIST_CLIP" and arg:
            promoted = self._clips.promote_chain(arg)
            log.info("CMD_PERSIST_CLIP:%s — no SD: %s",
                     arg, ",".join(promoted) or "nenhum")
        elif name == "CMD_BULK_UPLOAD":
            self._bulk_upload_spool()
        elif name == "CMD_SNAPSHOT":
            self._upload_snapshot_now()
        elif name == "CMD_LIVE":
            self._handle_live_cmd(arg)
        elif name == "CMD_ZOOM" and arg:
            self._handle_zoom_cmd(arg)
        elif name == "CMD_AUTOFOCUS":
            self._handle_autofocus_cmd()
        elif name == "CMD_GET_LOGS":
            self._send_logs(arg)
        elif name == "CMD_CALIBRATE":
            self._run_calibration(arg)
        elif name == "CMD_RECALIBRATE":
            self._recalibrate_requested = True
            log.info("CMD_RECALIBRATE: re-anchor do gate solicitado")
            self._post_status("recalibrate_requested")
        elif name == "CMD_HEALTH":
            self._post_keepalive()
        elif name == "CMD_RESTART_AGENT":
            log.warning("CMD_RESTART_AGENT: reiniciando o processo (systemd sobe de novo)")
            self._post_status("restart_agent")
            logging.shutdown()
            os._exit(0)
        elif name == "CMD_RESTART_BUFFER":
            self._restart_buffer()
        else:
            log.warning("Comando desconhecido: %s", cmd)

    def _restart_buffer(self) -> None:
        """Reinicia o cam-rtsp-buffer (recupera latest.jpg travado). Requer que
        o agente rode como root (ou sudoers para systemctl)."""
        try:
            subprocess.run(
                ["systemctl", "restart", "saira-rtsp-buffer"],
                check=True, capture_output=True, timeout=30,
            )
            log.info("CMD_RESTART_BUFFER: saira-rtsp-buffer reiniciado")
            self._post_status("restart_buffer ok")
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("CMD_RESTART_BUFFER falhou: %s", exc)
            self._post_status(f"restart_buffer fail: {exc}")

    def _clip_upload_timeout(self, size_bytes: int) -> int:
        """Timeout escalado pelo tamanho: a costura de uma cadeia pode chegar
        a centenas de MB e o 4G real sustenta ~50 KB/s no pior caso. Teto de
        900s para o watchdog continuar pegando hang de verdade."""
        return max(self.cfg.upload_timeout_s * 4, min(900, int(size_bytes / 50_000)))

    def _upload_event_clip(self, event_id: str) -> None:
        """CMD_VIDEO_CLIP:<event_id> — sobe o clipe (cadeia costurada) do evento."""
        path, is_temp = self._clips.export_clip(event_id)
        if path is None:
            log.warning("Clipe do evento %s indisponível (evicted/nunca arquivado)", event_id)
            self._post_status(f"video_unavailable:{event_id}")
            return
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        try:
            with path.open("rb") as fh:
                resp = self._ec2_session.post(
                    self.cfg.video_url,
                    params={"event_id": event_id},
                    data=fh,
                    headers={"Content-Type": "video/mp4"},
                    timeout=self._clip_upload_timeout(size),
                )
            log.info("Clipe %s enviado (%.1f MB) HTTP %s",
                     event_id, size / 1e6, resp.status_code)
        except requests.RequestException as exc:
            log.warning("Upload do clipe %s falhou: %s", event_id, exc)
        finally:
            self._clips.cleanup_export(path, is_temp)

    def _post_status(self, message: str) -> None:
        """Registra um evento de auditoria no servidor (best-effort)."""
        try:
            self._ec2_session.post(
                f"{self.cfg.ec2_base.rstrip('/')}/status",
                data={"message": f"{self.cfg.device_id}: {message}"},
                timeout=10,
            )
        except requests.RequestException:
            pass

    def _export_and_upload_ring(self) -> None:
        """CMD_VIDEO_CLIP sem argumento (legado): concatena os segmentos .ts
        recentes do buffer RTSP em um mp4 (sem reencode) e envia para
        POST /device/<id>/video."""
        seg_dir = self.cfg.video_seg_dir
        # segment_wrap recicla os nomes (seg_000..seg_NNN), então a ordem
        # cronológica vem do mtime, não do nome.
        segments = sorted(seg_dir.glob("seg_*.ts"), key=lambda s: s.stat().st_mtime)
        if not segments:
            log.warning("Sem segmentos de vídeo em %s", seg_dir)
            return
        # Mantém aproximadamente os últimos VIDEO_CLIP_SECONDS por mtime.
        cutoff = time.time() - self.cfg.video_clip_seconds
        recent = [s for s in segments if s.stat().st_mtime >= cutoff] or segments
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        list_file = seg_dir / f"clip_{ts}.txt"
        out_mp4 = Path("/tmp") / f"clip_{self.cfg.device_id}_{ts}.mp4"
        list_file.write_text("".join(f"file '{s.as_posix()}'\n" for s in recent), encoding="utf-8")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                 "-c", "copy", "-movflags", "+faststart", str(out_mp4)],
                check=True, capture_output=True, timeout=120,
            )
            with out_mp4.open("rb") as fh:
                resp = self._ec2_session.post(
                    self.cfg.video_url,
                    data=fh,
                    headers={"Content-Type": "video/mp4"},
                    timeout=self.cfg.upload_timeout_s * 4,
                )
            log.info("Clip enviado (%d segmentos) HTTP %s", len(recent), resp.status_code)
        except subprocess.CalledProcessError as exc:
            log.error("ffmpeg falhou: %s", exc.stderr.decode(errors="ignore")[:400])
        finally:
            list_file.unlink(missing_ok=True)
            out_mp4.unlink(missing_ok=True)

    def _bulk_upload_spool(self) -> None:
        """Envia todos os frames do ring como stream TLV para /bulk-upload
        (mesmo formato que a ESP32: [uint32 LE tamanho][JPEG])."""
        frames = sorted(self.cfg.spool_dir.glob("*.jpg"))
        if not frames:
            log.info("Bulk upload: nenhum frame no spool")
            return

        def gen() -> bytes:
            for f in frames:
                try:
                    blob = f.read_bytes()
                except OSError:
                    continue
                yield struct.pack("<I", len(blob)) + blob

        try:
            resp = self._ec2_session.post(
                self.cfg.bulk_upload_url,
                data=gen(),
                headers={"Content-Type": "application/octet-stream"},
                timeout=self.cfg.upload_timeout_s * 4,
            )
            log.info("Bulk upload %d frames HTTP %s", len(frames), resp.status_code)
        except requests.RequestException as exc:
            log.warning("Bulk upload falhou: %s", exc)


def main() -> None:
    cfg = load_config()
    setup_logging(cfg)
    agent = Agent(cfg)
    signal.signal(signal.SIGTERM, agent.stop)
    signal.signal(signal.SIGINT, agent.stop)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, agent.trigger_synthetic_event)
    agent.run()


if __name__ == "__main__":
    main()
