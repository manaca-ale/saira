# src/ingester/main.py
import os
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
import json
from datetime import datetime

from ingester import config
from ingester.local import adb_adapter

def setup_logging() -> None:
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

def _append_health_jsonl(payload: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    filepath = os.path.join(config.LOG_DIR, config.HEALTH_JSONL_FILENAME)
    with open(filepath, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")

def _check_memory_watchdog(serial: str, snapshot: dict | None, health_cycle_id: int) -> None:
    """Evaluate memory level and take preventive action if needed."""
    if not config.MEMORY_CHECK_ENABLED or not snapshot:
        return
    mem_kb = snapshot.get("mem_available_kb")
    if mem_kb is None:
        return

    if mem_kb < config.MEMORY_CRITICAL_THRESHOLD_KB:
        logging.critical(
            f"[health_cycle_id={health_cycle_id}] MEMORY CRITICAL: {mem_kb}KB available "
            f"(threshold={config.MEMORY_CRITICAL_THRESHOLD_KB}KB). Rebooting device {serial}."
        )
        try:
            adb_adapter.reboot_device(serial)
            adb_adapter.wait_for_device(serial, max_wait_s=config.MEMORY_POST_REBOOT_WAIT_SECONDS)
        except Exception as exc:
            logging.error(f"[health_cycle_id={health_cycle_id}] Failed to reboot device: {exc}")
        return

    if mem_kb < config.MEMORY_WARNING_THRESHOLD_KB:
        logging.warning(
            f"[health_cycle_id={health_cycle_id}] MEMORY WARNING: {mem_kb}KB available "
            f"(threshold={config.MEMORY_WARNING_THRESHOLD_KB}KB). Force-stopping ICSee on {serial}."
        )
        try:
            adb_adapter.close_app(serial, config.ICSEE_PACKAGE_NAME, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
        except Exception as exc:
            logging.error(f"[health_cycle_id={health_cycle_id}] Failed to force-stop app: {exc}")


def run_health_loop() -> None:
    health_cycle_id = 0
    last_uptime: float | None = None
    while True:
        start = time.time()
        health_cycle_id += 1
        errors: list[str] = []
        snapshot = None
        serial = None

        try:
            devices = adb_adapter.list_devices(timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise adb_adapter.AdbCommandError("adb devices", 1, "", "No devices")
            serial = devices[0]
            snapshot = adb_adapter.get_health_snapshot(serial, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            errors.extend(snapshot.pop("_errors", []))
        except Exception as exc:
            errors.append(str(exc))
            logging.error(f"[health_cycle_id={health_cycle_id}] Health loop error: {exc}", exc_info=True)

        # --- Reboot detection (uptime drop) ---
        if snapshot:
            current_uptime = snapshot.get("uptime_s")
            if current_uptime is not None and last_uptime is not None and current_uptime < last_uptime:
                logging.warning(
                    f"[health_cycle_id={health_cycle_id}] REBOOT DETECTED: uptime dropped "
                    f"from {last_uptime:.0f}s to {current_uptime:.0f}s"
                )
            if current_uptime is not None:
                last_uptime = current_uptime

        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "serial": serial,
            "health_cycle_id": health_cycle_id,
            "snapshot": snapshot,
            "errors": errors,
        }
        _append_health_jsonl(payload)

        # --- Memory watchdog ---
        if serial and snapshot:
            _check_memory_watchdog(serial, snapshot, health_cycle_id)

        elapsed = time.time() - start
        sleep_seconds = max(0, config.HEALTH_INTERVAL_SECONDS - elapsed)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

def main_aws():
    """
    Função placeholder para o modo de operação padrão (AWS SQS/S3).
    """
    logging.info("Modo AWS (SQS/S3) ativado. Nenhuma ação implementada ainda.")
    # Aqui entraria a lógica original de `cameras.py`, `sqs.py`, etc.
    pass

if __name__ == "__main__":
    setup_logging()
    # Verifica o modo de operação a partir de uma variável de ambiente
    ingester_mode = os.environ.get("INGESTER_MODE", "local").lower()

    if ingester_mode == "local":
        logging.info("Modo 'local' detectado. Iniciando captura via ADB.")
        # Importa e executa a lógica de captura local somente quando necessário
        health_thread = threading.Thread(target=run_health_loop, name="health-loop", daemon=True)
        health_thread.start()
        from ingester.local.capture import run_forever_loop
        run_forever_loop()
    elif ingester_mode == "aws":
        main_aws()
    else:
        logging.error(f"Modo de ingester desconhecido: '{ingester_mode}'. Use 'local' ou 'aws'.")
