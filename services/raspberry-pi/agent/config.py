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

# Intervalo mínimo absoluto entre frames no modo legado (sem motion gate).
MIN_CAPTURE_INTERVAL_S = 5.0
# Piso da cadência de ANÁLISE no modo motion (análise local não custa 4G;
# o que sobe é controlado por burst/heartbeat).
MIN_ANALYZE_INTERVAL_S = 1.0


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
    video_seg_seconds: int

    # Fonte do snapshot:
    #   auto = lê SNAPSHOT_JPG (mantido pelo cam-rtsp-buffer.sh a partir dos
    #          keyframes do RTSP) e cai para o snapshot HTTP se estiver velho
    #   rtsp = só o arquivo do RTSP   |   http = só o snapshot HTTP (legado)
    snapshot_source: str
    snapshot_jpg: Path
    snapshot_max_age_s: float

    # Polling de config remota e de comandos
    config_poll_interval_s: int
    command_poll_timeout_s: int

    # Motion gate (BGSUB streaming) — off | shadow | on
    motion_enabled: str
    idle_analyze_interval_s: float
    burst_upload_interval_s: float
    # Envio em lote dos frames do evento: 0/1 = legado (1 POST por frame);
    # >=2 = acumula até N frames e sobe num único POST /upload-batch (ou no
    # fim do evento). Bound do delay = N frames, independente da duração.
    event_batch_size: int
    heartbeat_interval_s: int
    warmup_seconds: int
    event_end_quiet_s: int
    event_max_s: int
    pile_zone_polygon: str  # JSON compacto (ref 1280x720); vazio = frame inteiro

    # Parâmetros BGSUB (já na escala do frame ANALISADO, 360p por padrão)
    pi_bgsub_history: int
    pi_bgsub_var_threshold: float
    pi_bgsub_shadow_threshold: int
    pi_bgsub_min_px_active: int
    pi_bgsub_delta_min_px: int
    # Limiar de MOVIMENTO para ABRIR evento (além do foreground). Recall-biased:
    # descarte de baixo contraste/na borda gera pouco fg mas a pessoa deposita
    # com movimento; sem isso o evento não abre e o ato cai no idle.
    pi_bgsub_delta_start_px: int
    pi_bgsub_consec_start: int
    pi_bgsub_lr_idle: float
    pi_bgsub_lr_recover: float
    pi_bgsub_recover_max_s: int
    # Pré-filtro transiente: se o evento FECHA com fg residual abaixo deste
    # valor, a zona voltou à baseline = nada NOVO foi depositado (foi só
    # passagem). O evento é marcado "end_transient" e o worker o descarta
    # sem chamar o Gemini. Descarte real fecha com fg alto (objeto recém-
    # largado, ainda não absorvido pelo MOG2) e passa normalmente.
    pi_event_min_residual_px: int

    # Ref_pré: enviar o frame "antes" (cena pré-intrusão) no início do evento,
    # dando à nuvem o par antes/depois para julgar incremento na pilha.
    pi_send_pre_frame: bool

    # Arquivo de clipes (RAM -> SD)
    archive_dir: Path
    archive_max_bytes: int
    clips_dir: Path
    clip_retention_days: int
    pre_roll_seconds: int
    tail_seconds: int

    # URLs derivadas
    upload_url: str = field(init=False)
    batch_upload_url: str = field(init=False)
    config_url: str = field(init=False)
    poll_url: str = field(init=False)
    bulk_upload_url: str = field(init=False)
    video_url: str = field(init=False)

    def __post_init__(self) -> None:
        base = self.ec2_base.rstrip("/")
        object.__setattr__(self, "upload_url", f"{base}/upload")
        object.__setattr__(self, "batch_upload_url", f"{base}/upload-batch")
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
        video_seg_seconds=_env_int("VIDEO_SEG_SECONDS", 2, minimum=1),
        snapshot_source=_env("SNAPSHOT_SOURCE", "auto").strip().lower(),
        snapshot_jpg=Path(_env("SNAPSHOT_JPG", "/dev/shm/saira/latest.jpg")),
        snapshot_max_age_s=_env_float("SNAPSHOT_MAX_AGE", 8.0, minimum=2.0),
        config_poll_interval_s=_env_int("CONFIG_POLL_INTERVAL", 60, minimum=10),
        command_poll_timeout_s=_env_int("COMMAND_POLL_TIMEOUT", 25, minimum=5),
        motion_enabled=_env("MOTION_ENABLED", "off").strip().lower(),
        idle_analyze_interval_s=_env_float(
            "IDLE_ANALYZE_INTERVAL", 2.0, minimum=MIN_ANALYZE_INTERVAL_S
        ),
        burst_upload_interval_s=_env_float("BURST_UPLOAD_INTERVAL", 1.5, minimum=0.5),
        event_batch_size=_env_int("EVENT_BATCH_SIZE", 0, minimum=0),
        heartbeat_interval_s=_env_int("HEARTBEAT_INTERVAL", 60, minimum=10),
        warmup_seconds=_env_int("WARMUP_SECONDS", 90, minimum=10),
        event_end_quiet_s=_env_int("EVENT_END_QUIET_SECONDS", 10, minimum=3),
        event_max_s=_env_int("EVENT_MAX_SECONDS", 120, minimum=30),
        pile_zone_polygon=_env("PILE_ZONE_POLYGON", "").strip(),
        pi_bgsub_history=_env_int("PI_BGSUB_HISTORY", 80, minimum=10),
        pi_bgsub_var_threshold=_env_float("PI_BGSUB_VAR_THRESHOLD", 40.0, minimum=1.0),
        pi_bgsub_shadow_threshold=_env_int("PI_BGSUB_SHADOW_THRESHOLD", 100, minimum=1),
        pi_bgsub_min_px_active=_env_int("PI_BGSUB_MIN_PX_ACTIVE", 200, minimum=10),
        pi_bgsub_delta_min_px=_env_int("PI_BGSUB_DELTA_MIN_PX", 100, minimum=10),
        pi_bgsub_delta_start_px=_env_int("PI_BGSUB_DELTA_START_PX", 120, minimum=10),
        pi_bgsub_consec_start=_env_int("PI_BGSUB_CONSEC_START", 2, minimum=1),
        pi_bgsub_lr_idle=_env_float("PI_BGSUB_LR_IDLE", 0.005, minimum=0.0),
        pi_bgsub_lr_recover=_env_float("PI_BGSUB_LR_RECOVER", 0.05, minimum=0.0),
        pi_bgsub_recover_max_s=_env_int("PI_BGSUB_RECOVER_MAX_S", 180, minimum=30),
        pi_event_min_residual_px=_env_int("PI_EVENT_MIN_RESIDUAL_PX", 250, minimum=0),
        pi_send_pre_frame=_env("PI_SEND_PRE_FRAME", "true").strip().lower()
        not in ("0", "false", "no", "off"),
        archive_dir=Path(_env("ARCHIVE_DIR", "/dev/shm/saira/archive")),
        archive_max_bytes=_env_int("ARCHIVE_MAX_BYTES", 200 * 1024 * 1024, minimum=16 * 1024 * 1024),
        clips_dir=Path(_env("CLIPS_DIR", "/var/lib/saira/clips")),
        clip_retention_days=_env_int("CLIP_RETENTION_DAYS", 7, minimum=1),
        pre_roll_seconds=_env_int("PRE_ROLL_SECONDS", 30, minimum=0),
        tail_seconds=_env_int("TAIL_SECONDS", 6, minimum=2),
    )
