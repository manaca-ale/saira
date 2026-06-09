#!/usr/bin/env python3
"""Agente de captura SAIRA para Raspberry Pi (relay de camera IP).

Substitui o papel da ESP32 (firmware/espcam-saira/src/ipcam_relay.cpp):
busca o snapshot da camera IP e repassa, byte a byte (pass-through, SEM
reencode), para o esp32-server na EC2. Mantem o mesmo contrato de rede,
entao worker/backend nao mudam.

Threads:
  - capture_loop   : a cada >=5s, faz fetch do snapshot e upload (com spool
                     local em caso de falha + drenagem de backlog).
  - config_loop    : poll de /device/<id>/config.txt (ETag) e aplica
                     timer_delay_ms / ip_cam_url / ip_cam_user / ip_cam_pass
                     em runtime, sem reiniciar.
  - command_loop   : long-poll de /device/<id>/poll; trata CMD_VIDEO_CLIP
                     (exporta o buffer RTSP recente) e CMD_BULK_UPLOAD
                     (envia o ring de frames como TLV).

Item BGSUB (#4) entra na FASE 2: ha um hook (motion_gate) que hoje sempre
deixa passar; a portabilidade do bgsub_filter.py (MOG2) sera plugada aqui.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from config import Config, MIN_CAPTURE_INTERVAL_S, load_config

log = logging.getLogger("saira-agent")

UPLOADED_SUFFIX = ".uploaded"


class Agent:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._stop = threading.Event()

        # Estado de runtime mutavel por config remota (protegido por lock).
        self._lock = threading.Lock()
        self._interval = cfg.capture_interval_s
        self._cam_url = cfg.ip_cam_url
        self._cam_user = cfg.ip_cam_user
        self._cam_pass = cfg.ip_cam_pass
        self._cam_auth = cfg.ip_cam_auth

        # Sessoes HTTP persistentes (keep-alive evita handshake por frame).
        self._cam_session = requests.Session()
        self._ec2_session = requests.Session()
        self._ec2_session.headers.update({"X-Device-Id": cfg.device_id})

        cfg.spool_dir.mkdir(parents=True, exist_ok=True)

    # ----- ciclo de vida -------------------------------------------------
    def stop(self, *_: object) -> None:
        log.info("Encerrando agente...")
        self._stop.set()

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.capture_loop, name="capture", daemon=True),
            threading.Thread(target=self.config_loop, name="config", daemon=True),
            threading.Thread(target=self.command_loop, name="command", daemon=True),
        ]
        for t in threads:
            t.start()
        log.info(
            "Agente iniciado device=%s cam=%s -> %s (intervalo=%.1fs)",
            self.cfg.device_id, self._cam_url, self.cfg.upload_url, self._interval,
        )
        while not self._stop.is_set():
            self._stop.wait(1.0)
        for t in threads:
            t.join(timeout=5.0)

    # ----- captura -------------------------------------------------------
    def capture_loop(self) -> None:
        next_at = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now < next_at:
                self._stop.wait(min(next_at - now, 0.5))
                continue
            with self._lock:
                interval = max(MIN_CAPTURE_INTERVAL_S, self._interval)
            next_at += interval
            if next_at < now:  # guarda contra drift apos atraso longo
                next_at = now + interval
            try:
                self._capture_once()
            except Exception:  # noqa: BLE001 - loop nunca pode morrer
                log.exception("Falha inesperada no ciclo de captura")

    def _capture_once(self) -> None:
        data = self._fetch_snapshot()
        if not data:
            self._drain_backlog()
            return
        if not self._motion_gate(data):  # FASE 2: BGSUB; hoje sempre True
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        frame_path = self.cfg.spool_dir / f"{ts}.jpg"
        tmp = frame_path.with_suffix(".jpg.tmp")
        tmp.write_bytes(data)
        tmp.replace(frame_path)
        self._prune_spool()
        # Sobe o frame recem-capturado primeiro; depois drena backlog antigo.
        if self._upload_frame(frame_path):
            self._drain_backlog()

    def _fetch_snapshot(self) -> bytes | None:
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
                log.warning("Snapshot invalido (%d bytes)", len(body))
                return None
            return body
        return None

    def _motion_gate(self, _data: bytes) -> bool:
        """Hook do filtro de movimento (FASE 2 — BGSUB/MOG2).

        Hoje sempre deixa passar. A portabilidade de
        services/yolo-worker-vm/src/worker/bgsub_filter.py sera plugada aqui:
        decodifica o JPEG, roda o MOG2 + zona, e retorna False para suprimir
        frames sem movimento persistente (economiza 4G).
        """
        return True

    # ----- upload / spool ------------------------------------------------
    def _upload_frame(self, frame_path: Path) -> bool:
        try:
            data = frame_path.read_bytes()
        except OSError:
            return False
        files = {"imageFile": ("snapshot.jpg", data, "image/jpeg")}
        try:
            resp = self._ec2_session.post(
                self.cfg.upload_url, files=files, timeout=self.cfg.upload_timeout_s
            )
        except requests.RequestException as exc:
            log.warning("Upload falhou (%s): %s — frame fica no spool", frame_path.name, exc)
            return False
        if resp.status_code == 200:
            frame_path.with_name(frame_path.name + UPLOADED_SUFFIX).touch()
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
            try:
                if cmd == "CMD_VIDEO_CLIP":
                    self._export_and_upload_clip()
                elif cmd == "CMD_BULK_UPLOAD":
                    self._bulk_upload_spool()
                else:
                    log.warning("Comando desconhecido: %s", cmd)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao executar comando %s", cmd)

    def _export_and_upload_clip(self) -> None:
        """Concatena os segmentos .ts recentes do buffer RTSP em um mp4
        (sem reencode) e envia para POST /device/<id>/video."""
        seg_dir = self.cfg.video_seg_dir
        # segment_wrap recicla os nomes (seg_000..seg_NNN), entao a ordem
        # cronologica vem do mtime, nao do nome.
        segments = sorted(seg_dir.glob("seg_*.ts"), key=lambda s: s.stat().st_mtime)
        if not segments:
            log.warning("Sem segmentos de video em %s", seg_dir)
            return
        # Mantem aproximadamente os ultimos VIDEO_CLIP_SECONDS por mtime.
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
        import struct

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
    agent.run()


if __name__ == "__main__":
    main()
