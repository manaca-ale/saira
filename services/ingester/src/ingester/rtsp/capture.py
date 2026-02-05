"""
Modulo de captura RTSP para o Ingester SAIRA v2.0

Responsavel por:
- Conectar a cameras IP via RTSP
- Capturar frames em intervalos configurados
- Validar qualidade da imagem
- Fazer upload para S3 e notificar SQS
"""

import os
import cv2
import time
import logging
from datetime import datetime
from typing import Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

from tenacity import (
    retry,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from .. import config
from ..s3 import upload_image_to_s3
from ..sqs import send_ingestion_message
from ..local.image_validator import analyze_image, validate_screenshot

logger = logging.getLogger(__name__)

# Forcar TCP para evitar perdas em 4G
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'


@dataclass
class CameraConfig:
    """Configuracao de uma camera"""
    id: str
    rpa: int
    rtsp_url: str
    capture_interval_seconds: int = 300
    active: bool = True


@dataclass
class CaptureResult:
    """Resultado de uma captura"""
    success: bool
    camera_id: str
    timestamp: datetime
    s3_key: Optional[str] = None
    error: Optional[str] = None
    validation_status: str = "unknown"


class RTSPCapture:
    """
    Classe para captura de frames RTSP com resiliencia.

    Features:
    - Conexao com retry e exponential backoff
    - Limpeza de buffer para frame atual
    - Validacao de imagem (nao preta/branca)
    - Circuit breaker por camera
    """

    def __init__(
        self,
        timeout_ms: int = 10000,
        read_timeout_ms: int = 5000,
        buffer_clear_frames: int = 5
    ):
        self.timeout_ms = timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self.buffer_clear_frames = buffer_clear_frames

        # Circuit breaker state
        self._failures: dict[str, int] = {}
        self._disabled_until: dict[str, float] = {}
        self._cb_threshold = config.CAMERA_CB_FAILURE_THRESHOLD
        self._cb_cooldown = config.CAMERA_CB_COOLDOWN_SECONDS

    def is_camera_available(self, camera_id: str) -> bool:
        """Verifica se camera esta disponivel (circuit breaker)"""
        until = self._disabled_until.get(camera_id)
        if until is None:
            return True
        if time.monotonic() >= until:
            self._disabled_until.pop(camera_id, None)
            self._failures[camera_id] = 0
            logger.info(f"[CB] {camera_id} reabilitada")
            return True
        return False

    def record_success(self, camera_id: str):
        """Registra sucesso (reset circuit breaker)"""
        self._failures[camera_id] = 0
        self._disabled_until.pop(camera_id, None)

    def record_failure(self, camera_id: str):
        """Registra falha (incrementa circuit breaker)"""
        count = self._failures.get(camera_id, 0) + 1
        self._failures[camera_id] = count
        if count >= self._cb_threshold:
            until = time.monotonic() + self._cb_cooldown
            self._disabled_until[camera_id] = until
            logger.warning(
                f"[CB] {camera_id} desabilitada por {self._cb_cooldown}s "
                f"apos {count} falhas"
            )

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError, cv2.error)),
        wait=wait_exponential(multiplier=1.5, min=2, max=30),
        stop=(stop_after_attempt(3) | stop_after_delay(45)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    def _connect(self, rtsp_url: str) -> cv2.VideoCapture:
        """Conecta a stream RTSP com retry"""
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.timeout_ms)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms)

        if not cap.isOpened():
            raise ConnectionError(f"Falha ao abrir stream: {rtsp_url}")

        return cap

    def capture_frame(self, camera: CameraConfig) -> Tuple[bool, Optional[bytes], str]:
        """
        Captura um frame de uma camera.

        Returns:
            Tuple[success, jpeg_bytes, status_message]
        """
        if not self.is_camera_available(camera.id):
            return False, None, "camera_disabled_by_circuit_breaker"

        cap = None
        try:
            # Conectar com retry
            cap = self._connect(camera.rtsp_url)

            # Limpar buffer para pegar frame atual
            for _ in range(self.buffer_clear_frames):
                cap.grab()

            # Ler frame
            ret, frame = cap.read()
            if not ret or frame is None:
                raise ConnectionError("Falha ao ler frame")

            # Converter para JPEG em memoria
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
            success, jpeg_buffer = cv2.imencode('.jpg', frame, encode_params)

            if not success:
                return False, None, "encode_failed"

            jpeg_bytes = jpeg_buffer.tobytes()

            # Validar imagem (nao preta/branca)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp.write(jpeg_bytes)
                tmp_path = tmp.name

            try:
                stats = analyze_image(tmp_path)
                is_valid, validation_status = validate_screenshot(stats)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            if not is_valid:
                self.record_failure(camera.id)
                return False, None, validation_status

            self.record_success(camera.id)
            return True, jpeg_bytes, "ok"

        except Exception as e:
            self.record_failure(camera.id)
            logger.error(f"Capture error {camera.id}: {e}")
            return False, None, str(e)

        finally:
            if cap is not None:
                cap.release()


def generate_s3_key(camera_id: str, timestamp: datetime) -> str:
    """Gera chave S3 no formato: raw/YYYY/MM/DD/camera_id_HHMMSS.jpg"""
    return (
        f"raw/{timestamp.strftime('%Y/%m/%d')}/"
        f"{camera_id}_{timestamp.strftime('%H%M%S')}.jpg"
    )


def run_capture_cycle(cameras: list[CameraConfig]) -> list[CaptureResult]:
    """
    Executa um ciclo de captura para todas as cameras.

    Returns:
        Lista de resultados de captura
    """
    rtsp = RTSPCapture()
    results = []

    for camera in cameras:
        if not camera.active:
            continue

        timestamp = datetime.utcnow()
        logger.info(f"Capturing {camera.id}...")

        success, jpeg_bytes, status = rtsp.capture_frame(camera)

        result = CaptureResult(
            success=False,
            camera_id=camera.id,
            timestamp=timestamp,
            validation_status=status
        )

        if success and jpeg_bytes:
            try:
                # Upload para S3
                s3_key = generate_s3_key(camera.id, timestamp)
                upload_image_to_s3(
                    data=jpeg_bytes,
                    bucket=config.S3_LANDING_ZONE_BUCKET,
                    key=s3_key
                )

                # Notificar SQS
                send_ingestion_message(
                    camera_id=camera.id,
                    s3_bucket=config.S3_LANDING_ZONE_BUCKET,
                    s3_key=s3_key,
                    metadata={
                        "rpa": camera.rpa,
                        "source": "ingester-rtsp-v2"
                    }
                )

                result.success = True
                result.s3_key = s3_key
                logger.info(f"OK {camera.id} -> s3://{config.S3_LANDING_ZONE_BUCKET}/{s3_key}")

            except Exception as e:
                result.error = str(e)
                logger.error(f"FAIL {camera.id} upload/sqs error: {e}")
        else:
            result.error = status
            logger.warning(f"FAIL {camera.id}: {status}")

        results.append(result)

    return results
