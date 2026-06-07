"""Configuracao do agente SAIRA na Raspberry Pi.

Le variaveis de ambiente (opcionalmente de um arquivo .env ao lado deste
modulo ou apontado por SAIRA_ENV_FILE) e expoe um objeto Config imutavel
para o restante do daemon.

O agente espelha o contrato que a ESP32 (ipcam_relay.cpp) usa contra o
esp32-server: snapshot HTTP da camera IP -> POST multipart /upload com
header X-Device-Id. Aqui nao ha reencode: o JPEG recebido da camera segue
byte a byte para a EC2 (pass-through puro).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Intervalo minimo absoluto entre frames (requisito do produto: nunca < 5s).
MIN_CAPTURE_INTERVAL_S = 5.0


def _load_env_file() -> None:
    """Carrega pares KEY=VALUE de um .env simples para os.environ.

    Nao sobrescreve variaveis ja definidas no ambiente (precedencia do
    systemd/Environment=). Evita dependencia de python-dotenv.
    """
    candidate = os.environ.get("SAIRA_ENV_FILE")
    paths = [Path(candidate)] if candidate else []
    paths.append(Path(__file__).resolve().parent / ".env")
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        break


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None and value < minimum:
        value = minimum
    return value


def _env_float(name: str, default: float, minimum: float | None = None) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    if minimum is not None and value < minimum:
        value = minimum
    return value


@dataclass(frozen=True)
class Config:
    # Identidade / destino
    device_id: str
    ec2_base: str  # ex: http://10.8.0.1:5002 (dentro do tunel WireGuard, sem TLS)

    # Camera IP (relay) — defaults iguais ao ipcam_relay.cpp
    ip_cam_url: str
    ip_cam_user: str
    ip_cam_pass: str
    ip_cam_auth: str  # none | basic | digest | auto
    rtsp_url: str

    # Cadencia
    capture_interval_s: float
    upload_timeout_s: int
    cam_timeout_s: int

    # Buffer local de frames (resiliencia offline + CMD_BULK_UPLOAD)
    spool_dir: Path
    keep_frames: int
    backlog_per_cycle: int  # quantos frames atrasados drenar por ciclo

    # Buffer de video (RTSP) e clip sob demanda
    video_seg_dir: Path
    video_clip_seconds: int

    # Polling de config remota e de comandos
    config_poll_interval_s: int
    command_poll_timeout_s: int

    # URLs derivadas
    upload_url: str = field(init=False)
    config_url: str = field(init=False)
    poll_url: str = field(init=False)
    bulk_upload_url: str = field(init=False)
    video_url: str = field(init=False)

    def __post_init__(self) -> None:
        base = self.ec2_base.rstrip("/")
        object.__setattr__(self, "upload_url", f"{base}/upload")
        object.__setattr__(self, "config_url", f"{base}/device/{self.device_id}/config.txt")
        object.__setattr__(self, "poll_url", f"{base}/device/{self.device_id}/poll")
        object.__setattr__(self, "bulk_upload_url", f"{base}/device/{self.device_id}/bulk-upload")
        object.__setattr__(self, "video_url", f"{base}/device/{self.device_id}/video")


def load_config() -> Config:
    _load_env_file()
    return Config(
        device_id=_env("DEVICE_ID", "pi-cam-001"),
        ec2_base=_env("EC2_BASE", "http://10.8.0.1:5002"),
        ip_cam_url=_env("IP_CAM_URL", "http://192.168.0.142:80/snap.jpg"),
        ip_cam_user=_env("IP_CAM_USER", "admin"),
        ip_cam_pass=_env("IP_CAM_PASS", "admin"),
        ip_cam_auth=_env("IP_CAM_AUTH", "auto").lower(),
        rtsp_url=_env("RTSP_URL", "rtsp://admin:admin@192.168.0.142:554/stream1"),
        capture_interval_s=_env_float("CAPTURE_INTERVAL", MIN_CAPTURE_INTERVAL_S, minimum=MIN_CAPTURE_INTERVAL_S),
        upload_timeout_s=_env_int("UPLOAD_TIMEOUT", 30, minimum=1),
        cam_timeout_s=_env_int("CAM_TIMEOUT", 10, minimum=1),
        spool_dir=Path(_env("SPOOL_DIR", "/var/spool/saira/frames")),
        keep_frames=_env_int("KEEP_FRAMES", 40, minimum=1),
        backlog_per_cycle=_env_int("BACKLOG_PER_CYCLE", 5, minimum=1),
        video_seg_dir=Path(_env("VIDEO_SEG_DIR", "/dev/shm/saira/segments")),
        video_clip_seconds=_env_int("VIDEO_CLIP_SECONDS", 120, minimum=10),
        config_poll_interval_s=_env_int("CONFIG_POLL_INTERVAL", 60, minimum=10),
        command_poll_timeout_s=_env_int("COMMAND_POLL_TIMEOUT", 25, minimum=5),
    )
