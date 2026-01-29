# src/ingester/local/capture.py
import logging
import os
import time
from datetime import datetime

from . import adb_adapter
from .. import config

logger = logging.getLogger(__name__)

# Diretorio para salvar as capturas, relativo a raiz do projeto ingester.
SAVE_DIR = "data/captures"


def run_capture_batch(device_id: str | None = None):
    """
    Executa um fluxo de captura para todas as cameras configuradas no app ICSee,
    que ja se presume aberto. Para cada camera, navega, estabiliza e captura.
    """
    logger.info("Iniciando fluxo de captura para todas as cameras (premissa: app ja esta aberto)...")

    os.makedirs(SAVE_DIR, exist_ok=True)
    active_device_id = device_id

    try:
        if not config.ASSUME_APP_OPEN:
            logger.error("Fluxo abortado: A configuracao 'ASSUME_APP_OPEN' esta como False. Este fluxo requer que a premissa seja verdadeira.")
            return

        if not active_device_id:
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            active_device_id = devices[0]

        logger.info(f"Usando o dispositivo: {active_device_id}")

        total_cameras = len(config.CAMERAS)
        logger.info(f"Encontradas {total_cameras} cameras para capturar.")

        for i, (camera_name, camera_conf) in enumerate(config.CAMERAS.items()):
            logger.info(f"--- [Camera {i+1}/{total_cameras}] Iniciando captura para: {camera_name} ---")

            try:
                # --- Etapa 1: Navegar ate a camera ---
                cam_coords = camera_conf["tap_coords"]
                logger.info(f"[{camera_name}] Acessando camera em (X={cam_coords['x']}, Y={cam_coords['y']})...")
                adb_adapter.tap(
                    active_device_id,
                    cam_coords["x"],
                    cam_coords["y"],
                    timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                )

                logger.info(f"[{camera_name}] Aguardando {config.WAIT_STREAM_LOAD_SECONDS}s para o stream carregar...")
                time.sleep(config.WAIT_STREAM_LOAD_SECONDS)

                # --- Etapa 2: Ritual de Estabilizacao Pre-Captura ---
                logger.info(f"[{camera_name}] Iniciando ritual de estabilizacao pre-captura...")
                for action in config.PRE_CAPTURE_SEQUENCE:
                    action_type = action["type"]
                    if action_type == "tap":
                        coords, label = action["coords"], action["label"]
                        logger.info(f"[{camera_name}] Ritual tap '{label}' em (X={coords['x']}, Y={coords['y']})...")
                        adb_adapter.tap(
                            active_device_id,
                            coords["x"],
                            coords["y"],
                            timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                        )
                    elif action_type == "wait":
                        duration = action["duration"]
                        logger.info(f"[{camera_name}] Ritual aguardando {duration}s...")
                        time.sleep(duration)
                logger.info(f"[{camera_name}] Ritual de estabilizacao concluido.")

                # --- Etapa 3: Capturar o Screenshot ---
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"capture_{camera_name}_{active_device_id}_{timestamp}.png"
                filepath = os.path.join(SAVE_DIR, filename)

                logger.info(f"[{camera_name}] Iniciando captura de screenshot para {filepath}...")
                success = adb_adapter.screencap(
                    active_device_id,
                    filepath,
                    timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                )
                if not success:
                    logger.error(f"[{camera_name}] O processo de captura de tela falhou.")
                else:
                    logger.info(f"[{camera_name}] Captura de screenshot finalizada com sucesso.")

                # --- Etapa 4: Acoes Pos-Captura (Retornar N Niveis) ---
                logger.info(f"[{camera_name}] Iniciando sequencia de retorno pos-captura...")
                for j in range(config.POST_CAPTURE_BACK_COUNT):
                    step = j + 1
                    logger.info(f"[{camera_name}] Executando BACK ({step}/{config.POST_CAPTURE_BACK_COUNT})...")
                    adb_adapter.press_key(
                        active_device_id,
                        "KEYCODE_BACK",
                        timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                    )
                    if step < config.POST_CAPTURE_BACK_COUNT:
                        logger.info(f"[{camera_name}] Aguardando {config.POST_BACK_DELAY_SECONDS}s...")
                        time.sleep(config.POST_BACK_DELAY_SECONDS)

                logger.info(f"--- [Camera {i+1}/{total_cameras}] Captura para {camera_name} concluida. ---")

            except Exception as e:
                logger.error(f"--- [Camera {i+1}/{total_cameras}] Ocorreu um erro inesperado ao processar '{camera_name}': {e} ---", exc_info=True)

            # Adiciona um delay entre as cameras para estabilizacao da UI, exceto apos a ultima.
            if i < total_cameras - 1:
                logger.info(f"Aguardando {config.INTER_CAMERA_DELAY_SECONDS}s antes de prosseguir para a proxima camera...")
                time.sleep(config.INTER_CAMERA_DELAY_SECONDS)

    except Exception as e:
        logger.critical(f"Ocorreu um erro critico no fluxo de captura principal: {e}", exc_info=True)
        raise

    finally:
        # A finalizacao ocorre uma vez apos o loop de todas as cameras.
        if active_device_id:
            logger.info("Fluxo de captura para todas as cameras finalizado. O aplicativo ICSee permanece aberto.")


def run_forever_loop():
    cycle_id = 0
    max_cycles = config.MAX_CYCLES
    if max_cycles == 0:
        max_cycles = None

    while True:
        cycle_id += 1
        cycle_start = time.time()
        logger.info(f"[cycle_id={cycle_id}] Ciclo iniciado.")
        cycle_error = None

        try:
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            device_id = devices[0]

            run_capture_batch(device_id=device_id)

        except Exception as exc:
            cycle_error = str(exc)
            logger.error(f"[cycle_id={cycle_id}] Erro no ciclo: {exc}", exc_info=True)
            logger.info(f"[cycle_id={cycle_id}] Aplicando backoff de {config.ERROR_BACKOFF_SECONDS}s.")
            time.sleep(config.ERROR_BACKOFF_SECONDS)
        finally:
            cycle_end = time.time()
            cycle_duration_s = round(cycle_end - cycle_start, 3)

            logger.info(f"[cycle_id={cycle_id}] Ciclo finalizado em {cycle_duration_s}s.")

            if not cycle_error:
                elapsed = cycle_end - cycle_start
                sleep_seconds = max(0, config.CAPTURE_INTERVAL_SECONDS - elapsed)
                if sleep_seconds > 0:
                    logger.info(f"[cycle_id={cycle_id}] Dormindo {sleep_seconds:.1f}s ate o proximo ciclo.")
                    time.sleep(sleep_seconds)

        if not config.RUN_FOREVER and max_cycles and cycle_id >= max_cycles:
            logger.info(f"[cycle_id={cycle_id}] Encerrando loop (MAX_CYCLES atingido).")
            break


def run_capture():
    """Executa o fluxo de captura para todas as cameras configuradas."""
    run_capture_batch()


if __name__ == "__main__":
    run_capture()
