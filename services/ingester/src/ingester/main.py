# src/ingester/main.py
"""
Ingester service - Captura frames de câmeras RTSP e envia para S3/SQS.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
import time

from ingester import config


def setup_logging() -> None:
    """Configura logging com arquivo rotativo e console."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []

    file_handler = RotatingFileHandler(
        os.path.join(config.LOG_DIR, "ingester.log"),
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def main():
    """Loop principal do ingester - captura RTSP e envia para AWS."""
    from .cameras import load_cameras
    from .rtsp.capture import run_capture_cycle

    logging.info("Iniciando Ingester (RTSP/AWS)")
    logging.info(f"S3 Bucket: {config.S3_LANDING_ZONE_BUCKET}")
    logging.info(f"SQS Queue: {config.SQS_INGESTION_QUEUE_URL or 'não configurada'}")
    logging.info(f"Intervalo de captura: {config.CAPTURE_INTERVAL_SECONDS}s")

    cameras = load_cameras(config.CAMERAS_CONFIG_PATH)
    active_cameras = [c for c in cameras if c.active]

    if not active_cameras:
        logging.error("Nenhuma câmera ativa configurada!")
        return

    logging.info(f"Câmeras ativas: {[c.id for c in active_cameras]}")

    cycle_count = 0
    consecutive_failures = 0
    max_consecutive_failures = config.CIRCUIT_BREAKER_FAILURE_THRESHOLD

    while config.RUN_FOREVER or (config.MAX_CYCLES and cycle_count < config.MAX_CYCLES):
        cycle_count += 1
        logging.info(f"=== Ciclo {cycle_count} ===")

        try:
            results = run_capture_cycle(active_cameras)

            successes = sum(1 for r in results if r.success)
            failures = len(results) - successes

            logging.info(f"Ciclo {cycle_count} completo: {successes} OK, {failures} falhas")

            if successes > 0:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logging.warning(f"Falhas consecutivas: {consecutive_failures}/{max_consecutive_failures}")

            if consecutive_failures >= max_consecutive_failures:
                logging.critical(f"Atingido limite de {consecutive_failures} ciclos sem sucesso. Encerrando.")
                break

        except Exception as e:
            logging.exception(f"Erro no ciclo {cycle_count}: {e}")
            consecutive_failures += 1

        if config.RUN_FOREVER or (config.MAX_CYCLES and cycle_count < config.MAX_CYCLES):
            logging.info(f"Aguardando {config.CAPTURE_INTERVAL_SECONDS}s até próximo ciclo...")
            time.sleep(config.CAPTURE_INTERVAL_SECONDS)

    logging.info("Ingester encerrado.")


if __name__ == "__main__":
    setup_logging()
    main()
