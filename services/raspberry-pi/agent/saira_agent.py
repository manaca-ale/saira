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
                       CMD_VIDEO_CLIP:<event_id> -> sobe o clipe do evento
                       CMD_PERSIST_CLIP:<event_id> -> RAM -> SD
                       CMD_BULK_UPLOAD           -> envia o spool como TLV
  - maintenance    : retenção dos clipes no SD (ClipStore.prune).

Clipes de evento: ver clip_store.py (RAM-first; SD só após confirmação do
worker; upload só quando a plataforma requisita).

Hook de teste: SIGUSR1 injeta um evento sintético (~10s de burst + arquivo
de clipe), útil para validar o pipeline sem movimento real.
"""

from __future__ import annotations

import logging
import os
import signal
import struct
import subprocess
import threading
import time
from datetime import datetime
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
        )

        # Rastreio de eventos correntes (para timestamps do clipe).
        self._event_start_ts: dict[str, float] = {}
        self._last_upload_at = 0.0

        # Snapshot via RTSP (latest.jpg do cam-rtsp-buffer.sh).
        self._last_snapshot_mtime = 0.0
        self._stale_snapshot_warned = False

        # Evento sintético (SIGUSR1).
        self._synthetic_id: Optional[str] = None
        self._synthetic_start = 0.0
        self._synthetic_until = 0.0
        self._synthetic_start_sent = False

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

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.capture_loop, name="capture", daemon=True),
            threading.Thread(target=self.config_loop, name="config", daemon=True),
            threading.Thread(target=self.command_loop, name="command", daemon=True),
            threading.Thread(target=self.maintenance_loop, name="maint", daemon=True),
        ]
        for t in threads:
            t.start()
        log.info(
            "Agente iniciado device=%s cam=%s -> %s (modo=%s, análise=%.1fs)",
            self.cfg.device_id, self._cam_url, self.cfg.upload_url,
            self._motion_mode, self._capture_cadence(),
        )
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
            interval = self._capture_cadence()
            now = time.monotonic()
            wait = (last_at + interval) - now
            if wait > 0:
                self._stop.wait(min(wait, 0.5))
                continue
            last_at = now
            try:
                self._capture_once()
            except Exception:  # noqa: BLE001 - loop nunca pode morrer
                log.exception("Falha inesperada no ciclo de captura")

    def _capture_once(self) -> None:
        data = self._fetch_snapshot()
        if not data:
            self._drain_backlog()
            return

        now = time.time()
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
        if decision.action == "start" and not decision.is_warmup:
            self._event_start_ts[decision.event_id] = now
        if decision.action in ("start", "end"):
            log.info(
                "[gate:%s] %s %s fg_px=%d delta_px=%d",
                mode, decision.event_id, decision.action,
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
        if decision.action == "end":
            # Frame de fechamento sobe sempre (fecha o manifest no servidor).
            self._spool_and_upload(data, event_id=decision.event_id, event_state="end")
            if not decision.is_warmup:
                self._schedule_archive(decision.event_id, end_ts=now)
            return

        if decision.event_id is not None and decision.action in ("start", "active"):
            min_gap = WARMUP_UPLOAD_INTERVAL_S if decision.is_warmup else max(
                0.5, self._burst_interval
            )
            if decision.action == "start" or now - self._last_upload_at >= min_gap:
                state = "start" if decision.action == "start" else "active"
                self._spool_and_upload(data, event_id=decision.event_id, event_state=state)
            return

        # idle/recover: heartbeat esparso mantém câmera "online" no painel.
        if now - self._last_upload_at >= self._heartbeat_interval:
            self._spool_and_upload(data)

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
            delay, self._clips.archive_event, args=(event_id, start_ts, end_ts)
        )
        timer.daemon = True
        timer.start()

    # Sentinela: o keyframe do RTSP ainda é o mesmo do ciclo anterior —
    # pula o ciclo SEM cair para o snapshot HTTP (que é flaky).
    _SAME_FRAME = object()

    def _fetch_snapshot(self) -> bytes | None:
        source = self.cfg.snapshot_source
        if source in ("auto", "rtsp"):
            res = self._fetch_snapshot_rtsp()
            if res is Agent._SAME_FRAME:
                return None
            if res is not None or source == "rtsp":
                return res
        return self._fetch_snapshot_http()

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
                log.warning("Erro ao buscar snapshot (%s): %s", mode, exc)
                return None
            if resp.status_code == 401 and auth_mode == "auto" and mode == "basic":
                continue  # tenta digest
            if resp.status_code != 200:
                log.warning("Snapshot HTTP %s (%s)", resp.status_code, mode)
                return None
            body = resp.content
            if len(body) < 500 or body[:2] != b"\xff\xd8":
                log.warning("Snapshot inválido (%d bytes)", len(body))
                return None
            return body
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
        tmp.write_bytes(data)
        tmp.replace(frame_path)
        self._prune_spool()
        # Sobe o frame recém-capturado primeiro; depois drena backlog antigo.
        if self._upload_frame(frame_path):
            self._drain_backlog()

    def _upload_frame(self, frame_path: Path) -> bool:
        try:
            data = frame_path.read_bytes()
        except OSError:
            return False
        files = {"imageFile": ("snapshot.jpg", data, "image/jpeg")}
        event_id, event_state = self._parse_spool_name(frame_path.name)
        form = {}
        if event_id:
            form = {"event_id": event_id, "event_state": event_state}
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
            log.info("Upload OK %s (%d bytes)", frame_path.name, len(data))
            return True
        log.warning("Upload HTTP %s (%s)", resp.status_code, frame_path.name)
        return False

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

    def _apply_config(self, body: str) -> None:
        kv: dict[str, str] = {}
        for line in body.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                kv[k.strip()] = v.strip()
        with self._lock:
            if "timer_delay_ms" in kv:
                try:
                    secs = int(kv["timer_delay_ms"]) / 1000.0
                    new = max(MIN_CAPTURE_INTERVAL_S, secs)
                    if new != self._interval:
                        log.info("Config: intervalo %.1fs -> %.1fs", self._interval, new)
                        self._interval = new
                except ValueError:
                    pass
            for key, attr in (("ip_cam_url", "_cam_url"), ("ip_cam_user", "_cam_user"), ("ip_cam_pass", "_cam_pass")):
                if key in kv and getattr(self, attr) != kv[key]:
                    log.info("Config: %s atualizado", key)
                    setattr(self, attr, kv[key])
            if "burst_interval_ms" in kv:
                try:
                    self._burst_interval = max(0.5, int(kv["burst_interval_ms"]) / 1000.0)
                except ValueError:
                    pass
            if "idle_analyze_interval_ms" in kv:
                try:
                    self._idle_analyze_interval = max(
                        MIN_ANALYZE_INTERVAL_S, int(kv["idle_analyze_interval_ms"]) / 1000.0
                    )
                except ValueError:
                    pass
            if "motion_enabled" in kv and kv["motion_enabled"] in ("off", "shadow", "on"):
                new_mode = kv["motion_enabled"]
                if new_mode != self._motion_mode:
                    if new_mode != "off" and self._gate is None:
                        self._gate = self._build_gate()
                    if new_mode == "off" or self._gate is not None:
                        log.info("Config: motion %s -> %s", self._motion_mode, new_mode)
                        self._motion_mode = new_mode

        # Tuning do gate (fora do lock do agente; gate é da thread de captura,
        # mas estes campos são leituras simples de int/float).
        if self._gate is not None:
            if "pile_zone_polygon" in kv:
                self._gate.set_polygon(kv["pile_zone_polygon"])
            for key, attr, cast in (
                ("motion_min_px_active", "min_px_active", int),
                ("motion_warmup_s", "warmup_seconds", int),
                ("event_max_s", "event_max_s", int),
                ("event_end_quiet_s", "event_end_quiet_s", int),
            ):
                if key in kv:
                    try:
                        setattr(self._gate, attr, cast(kv[key]))
                    except ValueError:
                        pass

    # ----- comandos sob demanda -----------------------------------------
    def command_loop(self) -> None:
        while not self._stop.is_set():
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
            try:
                if name == "CMD_VIDEO_CLIP" and arg:
                    self._upload_event_clip(arg)
                elif name == "CMD_VIDEO_CLIP":
                    self._export_and_upload_ring()
                elif name == "CMD_PERSIST_CLIP" and arg:
                    self._clips.persist_clip(arg)
                elif name == "CMD_BULK_UPLOAD":
                    self._bulk_upload_spool()
                else:
                    log.warning("Comando desconhecido: %s", cmd)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao executar comando %s", cmd)

    def _upload_event_clip(self, event_id: str) -> None:
        """CMD_VIDEO_CLIP:<event_id> — sobe o clipe arquivado do evento."""
        path, is_temp = self._clips.export_clip(event_id)
        if path is None:
            log.warning("Clipe do evento %s indisponível (evicted/nunca arquivado)", event_id)
            self._post_status(f"video_unavailable:{event_id}")
            return
        try:
            with path.open("rb") as fh:
                resp = self._ec2_session.post(
                    self.cfg.video_url,
                    params={"event_id": event_id},
                    data=fh,
                    headers={"Content-Type": "video/mp4"},
                    timeout=self.cfg.upload_timeout_s * 4,
                )
            log.info("Clipe %s enviado HTTP %s", event_id, resp.status_code)
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
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [%(threadName)s] %(message)s",
    )
    cfg = load_config()
    agent = Agent(cfg)
    signal.signal(signal.SIGTERM, agent.stop)
    signal.signal(signal.SIGINT, agent.stop)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, agent.trigger_synthetic_event)
    agent.run()


if __name__ == "__main__":
    main()
