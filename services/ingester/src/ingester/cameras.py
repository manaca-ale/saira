import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List
import logging

logger = logging.getLogger(__name__)


@dataclass
class CameraConfig:
    id: str
    rpa: int
    rtsp_url: str
    capture_interval_seconds: int = 300
    active: bool = True


def load_cameras(config_path: str = "config/cameras.yaml") -> List[CameraConfig]:
    """Carrega configuracao de cameras do YAML."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config nao encontrado: {config_path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    cameras = [CameraConfig(**cam) for cam in data.get("cameras", [])]
    active = [c for c in cameras if c.active]
    logger.info(f"Carregadas {len(active)}/{len(cameras)} cameras ativas")
    return cameras
