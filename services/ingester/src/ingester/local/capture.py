# src/ingester/local/capture.py
import logging
from logging.handlers import RotatingFileHandler
import os
import time
import json
import traceback
import shutil
from datetime import datetime

from PIL import Image

from . import adb_adapter, screen_classifier, screen_fingerprint
from .screen_classifier import ScreenState
from .. import config

logger = logging.getLogger(__name__)


def _ensure_logging() -> None:
    if logging.getLogger().handlers:
        return
    os.makedirs(config.LOG_DIR, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

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


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _append_jsonl(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _read_control_state() -> dict:
    path = config.CONTROL_JSON_PATH
    if not os.path.exists(path):
        return {"pause": False, "stop": False, "run_once": False}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"pause": False, "stop": False, "run_once": False}
    return {
        "pause": bool(data.get("pause", False)),
        "stop": bool(data.get("stop", False)),
        "run_once": bool(data.get("run_once", False)),
    }


def _write_control_state(state: dict) -> None:
    os.makedirs(config.LOG_DIR, exist_ok=True)
    with open(config.CONTROL_JSON_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2)


def _step_start(name: str) -> dict:
    return {"name": name, "ok": False, "start": _now_iso(), "end": None, "duration_ms": None, "details": None}


def _step_end(step: dict, ok: bool, details: str | None = None) -> dict:
    step["ok"] = ok
    step["end"] = _now_iso()
    step["duration_ms"] = _duration_ms(step["start"], step["end"])
    if details:
        step["details"] = details
    return step


def _duration_ms(start_iso: str, end_iso: str) -> int:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    return int((end - start).total_seconds() * 1000)


def _validate_focus(focus: dict) -> tuple[bool, str]:
    pkg = focus.get("package")
    activity = focus.get("activity")
    if pkg != config.EXPECTED_PACKAGE:
        return False, f"focus_package_mismatch:{pkg}"
    if activity not in config.EXPECTED_ACTIVITIES:
        return False, f"focus_activity_mismatch:{activity}"
    return True, "ok"


def _analyze_image(path: str) -> dict:
    with Image.open(path) as img:
        gray = img.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    min_v = min(pixels)
    max_v = max(pixels)
    variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
    std = variance ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2), "min": min_v, "max": max_v}


def _validate_screenshot(stats: dict) -> tuple[bool, str]:
    mean = stats["mean"]
    std = stats["std"]
    if mean <= config.BLACK_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_black_screen"
    if mean >= config.WHITE_MEAN_THRESHOLD and std <= config.LOW_STD_THRESHOLD:
        return False, "probable_white_screen"
    return True, "ok"


def _write_error_artifacts(cycle_id: str, device_id: str, health: dict | None, screenshot_path: str | None) -> str:
    base_dir = os.path.join(config.LOG_DIR, f"cycle_{cycle_id}_artifacts")
    os.makedirs(base_dir, exist_ok=True)

    window_txt = os.path.join(base_dir, "window.txt")
    logcat_txt = os.path.join(base_dir, "logcat.txt")
    health_json = os.path.join(base_dir, "health.json")

    if config.ENABLE_FOCUS_VALIDATION:
        try:
            window_dump = adb_adapter.get_window_dump(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            with open(window_txt, "w", encoding="utf-8") as handle:
                handle.write(window_dump)
        except Exception as exc:
            logger.error(f"Failed to write window.txt: {exc}", exc_info=True)
    else:
        logger.info("Skipping window.txt artifact (focus validation disabled).")

    try:
        logcat = adb_adapter.get_logcat_tail(device_id, config.LOGCAT_LINES_ON_ERROR, config.HEALTH_ADB_TIMEOUT_SECONDS)
        with open(logcat_txt, "w", encoding="utf-8") as handle:
            handle.write(logcat)
    except Exception as exc:
        logger.error(f"Failed to write logcat.txt: {exc}", exc_info=True)

    try:
        with open(health_json, "w", encoding="utf-8") as handle:
            json.dump(health or {}, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        logger.error(f"Failed to write health.json: {exc}", exc_info=True)

    if screenshot_path and os.path.exists(screenshot_path):
        try:
            shutil.copyfile(screenshot_path, os.path.join(base_dir, "screenshot.png"))
        except Exception as exc:
            logger.error(f"Failed to copy screenshot: {exc}", exc_info=True)

    return base_dir


def _error_obj(error_message: str | None, error_type: str | None, steps: list[dict], trace: str | None = None) -> dict | None:
    if not error_message:
        return None
    step_name = steps[-1]["name"] if steps else None
    return {
        "type": error_type or "CycleError",
        "message": error_message,
        "step": step_name,
        "trace": trace,
    }


def _capture_with_validation(device_id: str, camera_name: str) -> dict:
    last_focus = None
    last_stats = None
    last_path = None
    validation_reason = None

    attempts = config.MAX_SCREEN_RETRIES + 1
    for attempt in range(1, attempts + 1):
        if config.ENABLE_FOCUS_VALIDATION:
            focus = adb_adapter.get_focus_info(device_id, timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS)
            last_focus = focus
            focus_ok, focus_reason = _validate_focus(focus)
            if not focus_ok:
                validation_reason = focus_reason
                if attempt < attempts:
                    time.sleep(config.RETRY_DELAY_SEC)
                    continue
                return {
                    "path": None,
                    "validated": False,
                    "validation_reason": validation_reason,
                    "stats": None,
                    "attempts": attempt,
                    "focus": last_focus,
                }
        else:
            if attempt == 1:
                logger.info("Focus validation disabled by config; skipping.")

        camera_dir = os.path.join(config.OUTPUT_DIR, camera_name)
        os.makedirs(camera_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"capture_{device_id}_{timestamp}_attempt{attempt}.png"
        filepath = os.path.join(camera_dir, filename)
        last_path = filepath

        success = adb_adapter.screencap(
            device_id,
            filepath,
            timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
        )
        if not success:
            validation_reason = "screencap_failed"
            if attempt < attempts:
                time.sleep(config.RETRY_DELAY_SEC)
                continue
            return {
                "path": filepath,
                "validated": False,
                "validation_reason": validation_reason,
                "stats": None,
                "attempts": attempt,
                "focus": last_focus,
            }

        stats = _analyze_image(filepath)
        last_stats = stats
        valid, reason = _validate_screenshot(stats)
        validation_reason = reason
        if valid:
            return {
                "path": filepath,
                "validated": True,
                "validation_reason": "ok",
                "stats": stats,
                "attempts": attempt,
                "focus": last_focus,
            }

        if attempt < attempts:
            try:
                os.remove(filepath)
            except OSError:
                pass
            time.sleep(config.RETRY_DELAY_SEC)

    return {
        "path": last_path,
        "validated": False,
        "validation_reason": validation_reason,
        "stats": last_stats,
        "attempts": attempts,
        "focus": last_focus,
    }


def _check_screen(device_id: str, expected: ScreenState, context: str) -> tuple[bool, ScreenState, str | None]:
    """Take a screenshot, classify screen state, compare to expected.

    Returns (match, actual_state, screenshot_path).
    Screenshot is deleted if state matches.
    """
    if not config.ENABLE_SCREEN_STATE_DETECTION:
        logger.info(f"[{context}] Deteccao de tela desabilitada; pulando verificacao.")
        return True, ScreenState.UNKNOWN, None

    state, _fp, path = screen_classifier.capture_and_detect(device_id, context)
    match = state == expected
    if match:
        logger.info(f"[{context}] Tela OK: {state.value}")
    else:
        logger.warning(f"[{context}] Tela inesperada: esperado={expected.value} detectado={state.value}")
    # Cleanup temp screenshot
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    return match, state, path


def _recover_to_camera_list(device_id: str, current: ScreenState) -> bool:
    """Try to navigate back to the CAMERA_LIST screen."""
    logger.info(f"Recuperacao: estado atual={current.value}, objetivo=camera_list")

    if current == ScreenState.HOME:
        logger.info("Recuperacao: HOME detectado, abrindo app...")
        for attempt in range(1, config.MAX_STATE_RECOVERY_ATTEMPTS + 1):
            logger.info(f"Recuperacao: tentativa {attempt}/{config.MAX_STATE_RECOVERY_ATTEMPTS} de abrir o app...")
            if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
                continue
            time.sleep(config.STATE_CHECK_WAIT_SECONDS)
            ok, state, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_launch_attempt{attempt}")
            if ok:
                return True
            # Se caiu numa sub-tela do app (não HOME), tenta BACK
            if state != ScreenState.HOME:
                adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, f"recovery_post_back_attempt{attempt}")
                if ok:
                    return True
            # Ainda HOME — esperar mais antes de tentar de novo
            logger.warning(f"Recuperacao: ainda em {state.value} apos tentativa {attempt}, aguardando antes de tentar novamente...")
            time.sleep(config.APP_LAUNCH_WAIT_SECONDS)
        return False

    if current == ScreenState.CAMERA_NORMAL:
        adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_normal")
        return ok

    if current == ScreenState.CAMERA_FULLSCREEN:
        for _ in range(2):
            adb_adapter.press_key(device_id, "KEYCODE_BACK", timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(config.POST_BACK_DELAY_SECONDS)
        time.sleep(config.STATE_CHECK_WAIT_SECONDS)
        ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_fullscreen")
        return ok

    # UNKNOWN — try HOME + launch
    logger.info("Recuperacao: estado desconhecido, tentando HOME + launch_app...")
    adb_adapter.go_home_keyevent(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    if not adb_adapter.launch_app(device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS):
        return False
    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
    ok, _, _ = _check_screen(device_id, ScreenState.CAMERA_LIST, "recovery_from_unknown")
    return ok


def _run_pre_capture_sequence(device_id: str, camera_name: str) -> None:
    """Try to enter fullscreen: direct tap, then menu + fullscreen if needed."""
    fs = config.FULLSCREEN_TAP_COORDS
    menu = config.MENU_TAP_COORDS

    logger.info(f"[{camera_name}] Tap direto fullscreen (X={fs['x']}, Y={fs['y']})...")
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)

    if not config.ENABLE_SCREEN_STATE_DETECTION:
        return

    state, _fp, path = screen_classifier.capture_and_detect(
        device_id, f"pre_capture_fullscreen_direct:{camera_name}"
    )
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

    if state == ScreenState.CAMERA_FULLSCREEN:
        return

    logger.info(f"[{camera_name}] Fullscreen direto falhou (estado={state.value}), abrindo menu...")
    adb_adapter.tap(device_id, menu["x"], menu["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
    adb_adapter.tap(device_id, fs["x"], fs["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)


def _is_loading_screen(screenshot_path: str) -> bool:
    """Check if the screenshot is a loading/black screen (stream not ready yet)."""
    stats = _analyze_image(screenshot_path)
    if stats["mean"] <= config.BLACK_MEAN_THRESHOLD and stats["std"] <= config.LOW_STD_THRESHOLD:
        return True

    fp = screen_fingerprint.extract_fingerprint(screenshot_path)
    ind = fp["indicators"]
    return (
        stats["mean"] <= config.LOADING_MEAN_MAX
        and ind.get("bright_ratio_center", 0.0) >= config.LOADING_BRIGHT_CENTER_MIN
    )


def _wait_for_stream(device_id: str, camera_name: str, cam_coords: dict) -> bool:
    """Poll the screen until the stream loads or timeout is reached.

    Checks:
      1. If CAMERA_LIST → tap didn't register, retry.
      2. If CAMERA_FULLSCREEN + black screen → loading, wait and retry.
      3. Otherwise → stream is ready.

    Returns True if stream loaded, False if timed out.
    """
    timeout = config.WAIT_STREAM_LOAD_SECONDS
    poll_interval = 5
    elapsed = 0.0

    def _cleanup(p):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

    while elapsed < timeout:
        state, _fp, path = screen_classifier.capture_and_detect(device_id, f"stream_poll:{camera_name}")

        # If we're back on camera list, the tap didn't register — retry
        if state == ScreenState.CAMERA_LIST:
            logger.warning(f"[{camera_name}] Ainda na lista de cameras, repetindo tap...")
            _cleanup(path)
            adb_adapter.tap(device_id, cam_coords["x"], cam_coords["y"], timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue

        # Loading check: only in CAMERA_FULLSCREEN (black screen with loading bar)
        if state == ScreenState.CAMERA_FULLSCREEN:
            if path and os.path.exists(path) and _is_loading_screen(path):
                logger.info(f"[{camera_name}] Tela de carregamento detectada, aguardando {poll_interval}s... ({elapsed:.0f}/{timeout}s)")
                _cleanup(path)
                time.sleep(poll_interval)
                elapsed += poll_interval
                continue

        # Not camera_list, not loading — stream is ready
        _cleanup(path)
        logger.info(f"[{camera_name}] Stream carregado (estado={state.value}, elapsed={elapsed:.0f}s)")
        return True

    logger.error(f"[{camera_name}] Timeout aguardando stream ({timeout}s)")
    return False


def run_capture_batch(device_id: str | None = None, steps: list[dict] | None = None) -> dict | None:
    """
    Executa um fluxo de captura para todas as cameras configuradas no app ICSee.
    Inclui verificacao de estado de tela e recuperacao automatica quando habilitado.
    """
    logger.info("Iniciando fluxo de captura para todas as cameras...")

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    active_device_id = device_id

    try:
        if not active_device_id:
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            active_device_id = devices[0]

        logger.info(f"Usando o dispositivo: {active_device_id}")

        # --- CHECKPOINT A: verificar se estamos na tela de lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_a:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "pre_cycle")
            if not ok:
                logger.warning(f"Checkpoint A: tela errada ({state.value}), tentando recuperar...")
                recovery_ok = _recover_to_camera_list(active_device_id, state)
                if steps is not None:
                    steps.append(_step_end(step, recovery_ok, f"recovery_from={state.value}"))
                if not recovery_ok:
                    raise RuntimeError(f"Checkpoint A falhou: nao conseguiu voltar para camera_list (estado={state.value})")
                logger.info("Checkpoint A: recuperacao bem-sucedida.")
            else:
                if steps is not None:
                    steps.append(_step_end(step, True, "camera_list_ok"))

        total_cameras = len(config.CAMERAS)
        logger.info(f"Encontradas {total_cameras} cameras para capturar.")

        last_screenshot_info = None
        for i, (camera_name, camera_conf) in enumerate(config.CAMERAS.items()):
            logger.info(f"--- [Camera {i+1}/{total_cameras}] Iniciando captura para: {camera_name} ---")

            try:
                # --- Etapa 1: Navegar ate a camera ---
                step = _step_start(f"camera:{camera_name}:tap")
                cam_coords = camera_conf["tap_coords"]
                logger.info(f"[{camera_name}] Acessando camera em (X={cam_coords['x']}, Y={cam_coords['y']})...")
                adb_adapter.tap(
                    active_device_id,
                    cam_coords["x"],
                    cam_coords["y"],
                    timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                )
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 2: Aguardar stream carregar (polling) ---
                # Em vez de esperar um tempo fixo, verificamos se a tela ainda
                # esta carregando (preta) ou se voltou para a lista de cameras.
                step = _step_start(f"camera:{camera_name}:wait_stream")
                stream_ready = _wait_for_stream(active_device_id, camera_name, cam_coords)
                if steps is not None:
                    steps.append(_step_end(step, stream_ready))
                if not stream_ready:
                    logger.warning(f"[{camera_name}] Stream timeout, voltando para HOME...")
                    adb_adapter.go_home_keyevent(active_device_id, timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
                    time.sleep(config.STATE_CHECK_WAIT_SECONDS)
                    raise RuntimeError(f"Stream nao carregou para {camera_name} dentro de {config.WAIT_STREAM_LOAD_SECONDS}s")

                # --- Etapa 3: Ritual de Estabilizacao Pre-Captura ---
                logger.info(f"[{camera_name}] Iniciando ritual de estabilizacao pre-captura...")
                step = _step_start(f"camera:{camera_name}:pre_capture")
                _run_pre_capture_sequence(active_device_id, camera_name)
                logger.info(f"[{camera_name}] Ritual de estabilizacao concluido.")
                if steps is not None:
                    steps.append(_step_end(step, True))

                # --- Etapa 4: Verificacao pre-captura ---
                # Conferir que estamos em fullscreen (nao em camera_list, loading, ou camera_normal)
                if config.ENABLE_SCREEN_STATE_DETECTION:
                    step = _step_start(f"camera:{camera_name}:pre_capture_check")
                    for retry in range(config.PRE_CAPTURE_RETRY_MAX + 1):
                        state, _fp, path = screen_classifier.capture_and_detect(
                            active_device_id, f"pre_capture_check:{camera_name}:r{retry}"
                        )
                        is_loading = (
                            state == ScreenState.CAMERA_FULLSCREEN
                            and path and os.path.exists(path)
                            and _is_loading_screen(path)
                        )
                        # Cleanup temp screenshot
                        try:
                            if path and os.path.exists(path):
                                os.remove(path)
                        except OSError:
                            pass

                        if state == ScreenState.CAMERA_LIST:
                            if steps is not None:
                                steps.append(_step_end(step, False, "voltou_para_camera_list"))
                            raise RuntimeError(f"[{camera_name}] Voltou para camera_list antes da captura")

                        if is_loading:
                            logger.warning(f"[{camera_name}] Tela de loading detectada antes da captura, aguardando 5s...")
                            time.sleep(5)
                            continue

                        if state == ScreenState.CAMERA_NORMAL:
                            if retry < config.PRE_CAPTURE_RETRY_MAX:
                                logger.warning(f"[{camera_name}] Ainda em camera_normal apos ritual (tentativa {retry+1}), repetindo ritual...")
                                _run_pre_capture_sequence(active_device_id, camera_name)
                                continue
                            else:
                                logger.error(f"[{camera_name}] Nao entrou em fullscreen apos {config.PRE_CAPTURE_RETRY_MAX+1} tentativas")
                                if steps is not None:
                                    steps.append(_step_end(step, False, "stuck_in_camera_normal"))
                                raise RuntimeError(f"[{camera_name}] Nao entrou em fullscreen apos ritual")

                        # CAMERA_FULLSCREEN (not loading) or UNKNOWN — proceed
                        break

                    if steps is not None and step.get("end") is None:
                        steps.append(_step_end(step, True, f"state={state.value}"))

                # --- Etapa 5: Capturar o Screenshot ---
                step = _step_start(f"camera:{camera_name}:screencap_validate")
                logger.info(f"[{camera_name}] Iniciando captura de screenshot com validacao...")
                screenshot_info = _capture_with_validation(active_device_id, camera_name)
                last_screenshot_info = screenshot_info
                if steps is not None:
                    steps.append(_step_end(step, screenshot_info.get("validated", False), screenshot_info.get("validation_reason")))
                if not screenshot_info.get("validated"):
                    raise RuntimeError(f"Screenshot invalid: {screenshot_info.get('validation_reason')}")

                # --- Etapa 4: Acoes Pos-Captura (Retornar N Niveis) ---
                logger.info(f"[{camera_name}] Iniciando sequencia de retorno pos-captura...")
                post_step = _step_start(f"camera:{camera_name}:post_back")
                for j in range(config.POST_CAPTURE_BACK_COUNT):
                    back_index = j + 1
                    logger.info(f"[{camera_name}] Executando BACK ({back_index}/{config.POST_CAPTURE_BACK_COUNT})...")
                    adb_adapter.press_key(
                        active_device_id,
                        "KEYCODE_BACK",
                        timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS,
                    )
                    if back_index < config.POST_CAPTURE_BACK_COUNT:
                        logger.info(f"[{camera_name}] Aguardando {config.POST_BACK_DELAY_SECONDS}s...")
                        time.sleep(config.POST_BACK_DELAY_SECONDS)
                if steps is not None:
                    steps.append(_step_end(post_step, True))

                logger.info(f"--- [Camera {i+1}/{total_cameras}] Captura para {camera_name} concluida. ---")

            except Exception as e:
                logger.error(f"--- [Camera {i+1}/{total_cameras}] Ocorreu um erro inesperado ao processar '{camera_name}': {e} ---", exc_info=True)
                raise

            # Adiciona um delay entre as cameras para estabilizacao da UI, exceto apos a ultima.
            if i < total_cameras - 1:
                logger.info(f"Aguardando {config.INTER_CAMERA_DELAY_SECONDS}s antes de prosseguir para a proxima camera...")
                time.sleep(config.INTER_CAMERA_DELAY_SECONDS)

        # --- CHECKPOINT C: verificar se voltamos para a lista de cameras ---
        if config.ENABLE_SCREEN_STATE_DETECTION:
            step = _step_start("checkpoint_c:verify_camera_list")
            ok, state, _ = _check_screen(active_device_id, ScreenState.CAMERA_LIST, "post_cycle")
            if steps is not None:
                steps.append(_step_end(step, ok, f"state={state.value}"))
            if not ok:
                logger.warning(f"Checkpoint C: ciclo terminou em estado inesperado ({state.value}). Informativo apenas.")

        return last_screenshot_info

    except Exception as e:
        logger.critical(f"Ocorreu um erro critico no fluxo de captura principal: {e}", exc_info=True)
        raise

    finally:
        if active_device_id:
            logger.info("Fluxo de captura para todas as cameras finalizado.")


def run_forever_loop():
    _ensure_logging()
    cycle_id = 0
    max_cycles = config.MAX_CYCLES
    if max_cycles == 0:
        max_cycles = None

    while True:
        control = _read_control_state()
        if control.get("stop"):
            logger.info("Controle: stop solicitado. Encerrando loop.")
            break
        if control.get("pause") and not control.get("run_once"):
            logger.info("Controle: pausa ativa. Aguardando para retomar...")
            time.sleep(5)
            continue
        run_once = control.get("run_once", False)

        cycle_id += 1
        cycle_start = time.time()
        cycle_id_str = f"{cycle_id}"
        ts_start = _now_iso()
        logger.info(f"[cycle_id={cycle_id}] Ciclo iniciado.")
        cycle_error = None
        cycle_error_type = None
        cycle_trace = None
        steps: list[dict] = []
        focus_info: dict | None = None
        health_snapshot: dict | None = None
        screenshot_info: dict | None = None
        device_id = None

        try:
            step = _step_start("health_check")
            devices = adb_adapter.list_devices(timeout_s=config.CAPTURE_ADB_TIMEOUT_SECONDS)
            if not devices:
                raise RuntimeError("Nenhum dispositivo encontrado para captura.")
            device_id = devices[0]
            if config.ENABLE_HEALTHCHECK:
                try:
                    health_snapshot = adb_adapter.get_health_snapshot(
                        device_id,
                        timeout_s=config.HEALTH_ADB_TIMEOUT_SECONDS,
                    )
                    steps.append(_step_end(step, True))
                except Exception as exc:
                    steps.append(_step_end(step, False, f"health_error:{exc}"))
                    health_snapshot = {"error": str(exc)}
                    logger.exception("Health check failed.")
            else:
                logger.info("Health check desabilitado por config; pulando coleta.")
                health_snapshot = {"disabled": True}
                steps.append(_step_end(step, True, "disabled_by_config"))

            step = _step_start("capture_batch")
            screenshot_info = run_capture_batch(device_id=device_id, steps=steps)
            focus_info = screenshot_info.get("focus") if screenshot_info else None
            steps.append(_step_end(step, True))

        except Exception as exc:
            cycle_error = str(exc)
            cycle_error_type = type(exc).__name__
            cycle_trace = traceback.format_exc()
            logger.error(f"[cycle_id={cycle_id}] Erro no ciclo: {exc}", exc_info=True)
            logger.info(f"[cycle_id={cycle_id}] Aplicando backoff de {config.ERROR_BACKOFF_SECONDS}s.")
            if device_id:
                _write_error_artifacts(cycle_id_str, device_id, health_snapshot, screenshot_info.get("path") if screenshot_info else None)
            time.sleep(config.ERROR_BACKOFF_SECONDS)
        finally:
            cycle_end = time.time()
            cycle_duration_s = round(cycle_end - cycle_start, 3)
            ts_end = _now_iso()

            event = {
                "cycle_id": cycle_id_str,
                "ts_start": ts_start,
                "ts_end": ts_end,
                "duration_ms": int(cycle_duration_s * 1000),
                "ok": cycle_error is None,
                "error": _error_obj(cycle_error, cycle_error_type, steps, cycle_trace),
                "steps": steps,
                "focus": focus_info,
                "health": health_snapshot,
                "screenshot": screenshot_info,
            }
            _append_jsonl(config.CYCLES_JSONL_PATH, event)

            logger.info(f"[cycle_id={cycle_id}] Ciclo finalizado em {cycle_duration_s}s.")

            if not cycle_error:
                elapsed = cycle_end - cycle_start
                sleep_seconds = max(0, config.CAPTURE_INTERVAL_SECONDS - elapsed)
                if sleep_seconds > 0:
                    logger.info(f"[cycle_id={cycle_id}] Dormindo {sleep_seconds:.1f}s ate o proximo ciclo.")
                    time.sleep(sleep_seconds)

        if run_once:
            control["run_once"] = False
            _write_control_state(control)

        if not config.RUN_FOREVER and max_cycles and cycle_id >= max_cycles:
            logger.info(f"[cycle_id={cycle_id}] Encerrando loop (MAX_CYCLES atingido).")
            break


def run_capture():
    """Executa o fluxo de captura para todas as cameras configuradas."""
    run_capture_batch()


if __name__ == "__main__":
    run_capture()
