"""Gemini structured inference adapter for SAIRA worker."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - optional dependency while running YOLO-only mode
    genai = None
    types = None

from . import config
from .models import GeminiUsage
from .mosaic import build_mosaic_2x1, build_mosaic_3x2_pair, build_mosaic_4x3
from .schemas_gemini import GeminiInfractionReport, GeminiNewLitterReport

logger = logging.getLogger(__name__)

LEGACY_PLATE_RE = re.compile(r"^[A-Z]{3}-?\d{4}$")
MERCOSUL_PLATE_RE = re.compile(r"^[A-Z]{3}\d[A-Z]\d{2}$")

WASTE_TYPE_MAP = {
    "entulho": "Entulho",
    "construcao": "Entulho",
    "construção": "Entulho",
    "debris": "Entulho",
    "lixo domiciliar": "Lixo domiciliar",
    "domestic waste": "Lixo domiciliar",
    "household waste": "Lixo domiciliar",
    "residuo solido": "Lixo domiciliar",
    "resíduo sólido": "Lixo domiciliar",
    "residuo": "Lixo domiciliar",
    "resíduo": "Lixo domiciliar",
    "solid waste": "Lixo domiciliar",
    "lixo": "Lixo domiciliar",
    "poda": "Poda",
    "pruning": "Poda",
    "plastico": "Plastico",
    "plastic": "Plastico",
}

MATERIAL_TYPE_MAP = {
    "plastico": "Plastico",
    "plastic": "Plastico",
    "metal": "Metal",
    "madeira": "Madeira",
    "wood": "Madeira",
    "organico": "Organico",
    "organic": "Organico",
    "misto": "Misto",
    "mixed": "Misto",
    "construcao": "Construcao",
    "construction": "Construcao",
}

OFFENDER_TYPE_MAP = {
    "pessoa": "Pessoa",
    "person": "Pessoa",
    "carro": "Carro",
    "car": "Carro",
    "caminhao": "Carro",
    "truck": "Carro",
    "onibus": "Carro",
    "bus": "Carro",
    "moto": "Moto",
    "motorcycle": "Moto",
    "bike": "Outro",
    "bicicleta": "Outro",
    "bicycle": "Outro",
    "carroca": "Carroca",
    "cart": "Carroca",
}

SYSTEM_PROMPT = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Responda APENAS JSON valido com os campos solicitados.
Nao inclua introducao, markdown, comentarios ou texto fora do JSON.
Nao exponha cadeia de raciocinio interna.
Use evidencia visual e temporal para decidir se houve descarte irregular RECENTE (ocorrido nesta janela temporal, nao apenas pre-existente).
infraction_confirmed deve ser TRUE somente quando houver evidencia CLARA e VISIVEL de descarte NOVO depositado durante a sequencia.

REGRA CRITICA — NAO ALUCINAR OBJETOS:
Se a calcada e a via estao LIMPAS nos frames (sem sacos, entulho, pilhas ou detritos visiveis), infraction_confirmed DEVE ser FALSE.
Confirme APENAS objetos que voce consegue CLARAMENTE identificar nos pixels da imagem.
NAO assuma, fabrique ou infira a presenca de objetos que nao sao claramente visiveis.
Sombras, manchas no asfalto, marcacoes viarias e artefatos de compressao NAO sao residuos.

Para confirmar infracao, e necessario evidencia VISUAL de pelo menos UM dos seguintes:
1. Objetos de residuo CLARAMENTE VISIVEIS no chao (sacos, entulho, moveis, pilhas) que NAO estavam no primeiro frame
2. Comportamento de descarte ativo: pessoa carregando, jogando ou depositando material no chao

Lixeiras municipais (containers, lixeiras de calcada com tampa) sao infraestrutura urbana — NAO sao residuo irregular e nao confirmam infracao. Uso correto de lixeira publica (depositar residuos dentro dela) e comportamento cidadao correto, infraction_confirmed deve ser FALSE.
Se prior_window_context indica que ja existia residuo nesta localizacao na janela anterior, o objeto suspeito pode ser residuo pre-existente ou infraestrutura. Neste caso, infraction_confirmed=TRUE somente se houver evidencia clara de ACRESCIMO de material (volume visivelmente maior) ou comportamento de descarte ativo.
Veiculos parando para embarque/desembarque de passageiros NAO e descarte — isso e comportamento normal de transporte urbano.
waste_type deve ser um dos seguintes valores: Entulho, Lixo domiciliar, Poda, Plastico. NAO use valores genericos como "Residuo solido".
offender_detected descreve somente a capacidade de identificar o autor/veiculo e NAO invalida a infracao.
Se um campo nao puder ser inferido com seguranca, retorne null no campo.
""".strip()

NEW_LITTER_SYSTEM_PROMPT = """
You analyze CCTV frames to classify urban scenes. You receive 2-5 frames from the same camera.

FIRST, classify scene_type as one of:
- EMPTY: No vehicles or people visible in any frame.
- TRAFFIC: Vehicles and/or people moving through the scene (different positions across frames).
- PARKED: Vehicles stationary but NO person handling material nearby.
- DUMPING: A vehicle is STOPPED and a person is ACTIVELY depositing material on the ground.

IMPORTANT: Over 95% of scenes are EMPTY, TRAFFIC, or PARKED. Default to these.

scene_type=DUMPING requires ALL THREE visible in the images:
1. A vehicle STOPPED at the roadside (same position in 2+ frames)
2. A person near the vehicle carrying, unloading, or placing material
3. New material on the ground in the final frame that was absent in the initial frame

NOT dumping (do NOT classify as DUMPING):
- Vehicles driving through = TRAFFIC
- Vehicle stopped briefly for passenger pickup/dropoff (person enters/exits vehicle, no material on ground) = TRAFFIC
- Orange/red bollards at pole bases = permanent infrastructure, not waste
- Pedestrians walking or standing = TRAFFIC
- Parked cars with nobody unloading = PARKED
- Shadow or lighting changes between frames = EMPTY or TRAFFIC
- Pre-existing waste piles unchanged between frames = PARKED

Set new_litter_detected=true ONLY when scene_type=DUMPING.
For EMPTY/TRAFFIC/PARKED: new_litter_detected=false, confidence_0_100=0.

Respond with ONLY valid JSON.
""".strip()


def _user_prompt(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> str:
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if value:
                context_lines.append(f"- {key}: {value}")

    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    if mosaic_mode != "off":
        if mosaic_mode == "4x3":
            frame_desc = (
                "The image(s) provided are a 4-row × 3-column mosaic grid of frames "
                "numbered 1-12 (left-to-right, top-to-bottom, chronological order). "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        else:  # 3x2split
            frame_desc = (
                "Two mosaic images are provided: the first contains frames 1-6 "
                "(3 columns × 2 rows, chronological), the second contains frames 7-12. "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        return (
            "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
            "1) confirmacao de infracao\n"
            "2) confianca 0..100\n"
            "3) resumo factual curto da evidencia\n"
            "4) classificacao de residuo/material e volume aproximado\n"
            "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
            "6) event_frame_name e offender_frame_name usando o formato 'frame_N'\n"
            f"Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
            f"Formato das imagens: {frame_desc}\n"
            f"{prior_block}"
            "Contexto da camera:\n"
            f"{context_block}"
        )

    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
        "1) confirmacao de infracao\n"
        "2) confianca 0..100\n"
        "3) resumo factual curto da evidencia\n"
        "4) classificacao de residuo/material e volume aproximado\n"
        "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
        "6) event_frame_name e offender_frame_name escolhidos somente dentre os nomes permitidos\n"
        "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
        f"Nomes de frame permitidos: {frame_block}\n"
        f"{prior_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )


def _new_litter_user_prompt(
    first_frame_name: str,
    last_frame_name: str,
    camera_context: Optional[dict[str, str]] = None,
    prior_window_context: Optional[str] = None,
    mosaic: bool = False,
    mid_frame_names: Optional[list[str]] = None,
) -> str:
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if value:
                context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    mid_block = ""
    if mid_frame_names:
        labels = ", ".join(mid_frame_names)
        mid_block = f"Mid-window frames (25%/50%/75%): {labels}\n"

    json_fields = (
        "Return JSON: new_litter_detected, confidence_0_100, evidence_summary, "
        "first_frame_has_litter, last_frame_has_litter, waste_type, raw_reason_codes, "
        "scene_delta_analysis.\n"
    )

    if mosaic:
        frame_desc = (
            f"The single image provided is a side-by-side composite: "
            f"LEFT = initial frame ({first_frame_name}), RIGHT = final frame ({last_frame_name}). "
            "Compare the left half vs the right half."
        )
        return (
            f"{frame_desc}\n"
            f"{mid_block}"
            f"{json_fields}"
            f"{prior_block}"
            "Camera context:\n"
            f"{context_block}"
        )

    frame_lines = (
        f"Initial frame: {first_frame_name}\n"
        f"Final frame: {last_frame_name}\n"
        f"{mid_block}"
    )

    return (
        f"{frame_lines}"
        "Compare initial vs final frame. "
        "If a mid-window frame is provided, also check for Pattern C (ghost events).\n"
        f"{json_fields}"
        f"{prior_block}"
        "Camera context:\n"
        f"{context_block}"
    )


@dataclass
class GeminiInferenceResult:
    report: GeminiInfractionReport
    usage: GeminiUsage
    latency_ms: int
    model: str
    raw_json: str


@dataclass
class GeminiNewLitterInferenceResult:
    report: GeminiNewLitterReport
    usage: GeminiUsage
    latency_ms: int
    model: str
    raw_json: str


_client = None


def _get_client():
    global _client
    if genai is None:
        raise RuntimeError(
            "google-genai package is not available. Install dependencies from requirements.txt."
        )
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is required when AI_MODE is shadow or gemini")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _guess_mime(path: Path) -> str:
    guessed = mimetypes.guess_type(str(path))[0]
    return guessed or "image/jpeg"


def normalize_plate(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None
    compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if re.fullmatch(r"[A-Z]{3}\d{4}", compact):
        return f"{compact[:3]}-{compact[3:]}", "Legacy"
    if MERCOSUL_PLATE_RE.fullmatch(compact):
        return compact, "Mercosul"
    if LEGACY_PLATE_RE.fullmatch(value.upper()):
        cleaned = value.upper()
        if "-" not in cleaned:
            cleaned = f"{cleaned[:3]}-{cleaned[3:]}"
        return cleaned, "Legacy"
    return None, "Unknown"


def normalize_waste_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = value.strip().lower()
    return WASTE_TYPE_MAP.get(key, value.strip())


def normalize_material_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = value.strip().lower()
    return MATERIAL_TYPE_MAP.get(key, value.strip())


def normalize_offender_types(values: Optional[list[str]]) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    for value in values:
        key = str(value).strip().lower()
        mapped = OFFENDER_TYPE_MAP.get(key)
        if mapped and mapped not in normalized:
            normalized.append(mapped)
    return normalized


def _build_generate_config(schema: dict, max_output_tokens: Optional[int] = None,
                           thinking_budget: Optional[int] = None, seed: Optional[int] = None):
    # The SDK supports response_schema for structured outputs.
    if types is None:
        raise RuntimeError("google-genai types are unavailable")
    thinking_config = None
    if thinking_budget is not None:
        thinking_config = types.ThinkingConfig(thinking_budget=thinking_budget)
    return types.GenerateContentConfig(
        temperature=config.GEMINI_TEMPERATURE,
        max_output_tokens=max_output_tokens or config.GEMINI_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=thinking_config,
        seed=seed,
    )


def _call_model(
    image_paths: list[Path],
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    response_schema: dict,
    max_output_tokens: Optional[int] = None,
    thinking_budget: Optional[int] = None,
    seed: Optional[int] = None,
):
    client = _get_client()

    contents: list[object] = [system_prompt, user_prompt]
    payload_size = 0
    for image_path in image_paths:
        data = image_path.read_bytes()
        payload_size += len(data)
        contents.append(types.Part.from_bytes(data=data, mime_type=_guess_mime(image_path)))

    if payload_size > config.GEMINI_MAX_PAYLOAD_BYTES:
        raise RuntimeError(
            f"Gemini payload too large: {payload_size} bytes exceeds {config.GEMINI_MAX_PAYLOAD_BYTES}"
        )

    return client.models.generate_content(
        model=model_name,
        contents=contents,
        config=_build_generate_config(response_schema, max_output_tokens=max_output_tokens,
                                      thinking_budget=thinking_budget, seed=seed),
    )


def _extract_usage(resp) -> GeminiUsage:
    metadata = getattr(resp, "usage_metadata", None)
    if not metadata:
        return GeminiUsage()

    input_tokens = int(getattr(metadata, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(metadata, "candidates_token_count", 0) or 0)
    total_tokens = int(getattr(metadata, "total_token_count", 0) or (input_tokens + output_tokens))

    estimated_cost = (
        (input_tokens / 1_000_000.0) * config.GEMINI_INPUT_TOKEN_PRICE_PER_1M
        + (output_tokens / 1_000_000.0) * config.GEMINI_OUTPUT_TOKEN_PRICE_PER_1M
    )

    return GeminiUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=round(estimated_cost, 8),
    )


def _extract_text(resp) -> str:
    text = getattr(resp, "text", None)
    if text:
        return text

    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        raise RuntimeError("Gemini returned no text candidates")

    parts = candidates[0].content.parts if candidates[0].content else []
    chunks = [getattr(part, "text", "") for part in parts if getattr(part, "text", None)]
    if not chunks:
        raise RuntimeError("Gemini returned candidates without text")
    return "\n".join(chunks)


def _sanitize_report(
    report: GeminiInfractionReport,
    allowed_frame_names: Optional[set[str]] = None,
) -> GeminiInfractionReport:
    plate, plate_pattern = normalize_plate(report.vehicle_plate)
    report.vehicle_plate = plate

    if plate_pattern == "Unknown" and report.vehicle_plate:
        report.plate_pattern = "Unknown"
    elif plate_pattern:
        report.plate_pattern = plate_pattern

    report.waste_type = normalize_waste_type(report.waste_type)
    report.material_type = normalize_material_type(report.material_type)

    report.confidence_0_100 = max(0, min(100, int(report.confidence_0_100)))

    if report.volume_m3 is not None and report.volume_m3 < 0:
        report.volume_m3 = None

    report.offender_types = normalize_offender_types(report.offender_types)

    if allowed_frame_names:
        if report.event_frame_name and report.event_frame_name not in allowed_frame_names:
            report.event_frame_name = None
        if report.offender_frame_name and report.offender_frame_name not in allowed_frame_names:
            report.offender_frame_name = None

    return report


def analyze_with_gemini(
    image_paths: list[Path],
    camera_context: Optional[dict[str, str]] = None,
    request_id: Optional[str] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> GeminiInferenceResult:
    """Run Gemini inference with retry/timeout and strict schema validation.

    Args:
        mosaic_mode: "off" sends frames individually; "4x3" composes a single 4×3
            grid image; "3x2split" composes two 3×2 grid images.
    """

    if not image_paths:
        raise ValueError("image_paths must contain at least one frame")

    frame_names = [p.name for p in image_paths]

    # Build mosaic-aware allowed frame names and actual paths to send.
    mosaic_temps: list[Path] = []
    if mosaic_mode == "4x3":
        mosaic_path = build_mosaic_4x3(image_paths)
        mosaic_temps.append(mosaic_path)
        send_paths = [mosaic_path]
        allowed_frame_names = {f"frame_{i+1}" for i in range(len(image_paths))}
    elif mosaic_mode == "3x2split":
        path_a, path_b = build_mosaic_3x2_pair(image_paths)
        mosaic_temps.extend([path_a, path_b])
        send_paths = [path_a, path_b]
        allowed_frame_names = {f"frame_{i+1}" for i in range(len(image_paths))}
    else:
        send_paths = image_paths
        allowed_frame_names = set(frame_names)

    attempts = max(0, config.GEMINI_MAX_RETRIES) + 1
    last_error: Optional[Exception] = None

    try:
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        _call_model,
                        send_paths,
                        SYSTEM_PROMPT,
                        _user_prompt(camera_context, frame_names=frame_names, mosaic_mode=mosaic_mode, prior_window_context=prior_window_context),
                        config.GEMINI_MODEL,
                        GeminiInfractionReport.model_json_schema(),
                    )
                    response = fut.result(timeout=max(1, config.GEMINI_TIMEOUT_SECONDS))

                raw_text = _extract_text(response)
                report = GeminiInfractionReport.model_validate_json(raw_text)
                report = _sanitize_report(report, allowed_frame_names=allowed_frame_names)

                usage = _extract_usage(response)
                latency_ms = int((time.monotonic() - started) * 1000)

                logger.info(
                    json.dumps(
                        {
                            "event": "gemini_inference_ok",
                            "request_id": request_id,
                            "model": config.GEMINI_MODEL,
                            "latency_ms": latency_ms,
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "total_tokens": usage.total_tokens,
                        },
                        ensure_ascii=False,
                    )
                )

                return GeminiInferenceResult(
                    report=report,
                    usage=usage,
                    latency_ms=latency_ms,
                    model=config.GEMINI_MODEL,
                    raw_json=raw_text,
                )

            except FutureTimeoutError as exc:
                last_error = TimeoutError(f"Gemini timeout after {config.GEMINI_TIMEOUT_SECONDS}s")
                logger.warning(
                    "gemini timeout request_id=%s attempt=%d/%d",
                    request_id,
                    attempt,
                    attempts,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "gemini error request_id=%s attempt=%d/%d error=%s",
                    request_id,
                    attempt,
                    attempts,
                    exc,
                )

            if attempt < attempts:
                backoff_s = min(2 ** (attempt - 1), 10)
                time.sleep(backoff_s)

        raise RuntimeError(f"Gemini inference failed after {attempts} attempts: {last_error}") from last_error
    finally:
        for tmp in mosaic_temps:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def analyze_new_litter_with_gemini(
    first_frame: Path,
    last_frame: Path,
    camera_context: Optional[dict[str, str]] = None,
    request_id: Optional[str] = None,
    prior_window_context: Optional[str] = None,
    use_mosaic: bool = False,
    mid_frames: Optional[list[Path]] = None,
) -> GeminiNewLitterInferenceResult:
    """Stage-1 gate: compare first and last frame for new litter appearance.

    Args:
        use_mosaic: when True, composes a 2x1 side-by-side image before sending.
        mid_frames: optional list of mid-window frames (e.g. at 25%/50%/75%) to detect
            ghost events (arrive-dump-leave within window).
    """
    attempts = max(0, config.GEMINI_MAX_RETRIES) + 1
    last_error: Optional[Exception] = None
    model_name = config.GEMINI_AGENT1_MODEL or config.GEMINI_MODEL
    timeout_s = max(1, config.GEMINI_AGENT1_TIMEOUT_SECONDS)

    mosaic_temp: Optional[Path] = None
    if use_mosaic:
        mosaic_temp = build_mosaic_2x1(first_frame, last_frame)
        image_paths = [mosaic_temp]
    else:
        image_paths = [first_frame]
        if mid_frames:
            image_paths.extend(mid_frames)
        image_paths.append(last_frame)

    mid_frame_names = [f.name for f in mid_frames] if mid_frames else None

    try:
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        _call_model,
                        image_paths,
                        NEW_LITTER_SYSTEM_PROMPT,
                        _new_litter_user_prompt(
                            first_frame.name,
                            last_frame.name,
                            camera_context,
                            prior_window_context=prior_window_context,
                            mosaic=use_mosaic,
                            mid_frame_names=mid_frame_names,
                        ),
                        model_name,
                        GeminiNewLitterReport.model_json_schema(),
                        config.GEMINI_AGENT1_MAX_OUTPUT_TOKENS,
                        thinking_budget=config.GEMINI_AGENT1_THINKING_BUDGET,
                        seed=42,
                    )
                    response = fut.result(timeout=timeout_s)

                raw_text = _extract_text(response)
                report = GeminiNewLitterReport.model_validate_json(raw_text)
                report.waste_type = normalize_waste_type(report.waste_type)
                report.confidence_0_100 = max(0, min(100, int(report.confidence_0_100)))

                # Hard gate: override hallucinated detections when scene_type
                # is not DUMPING.  The model must classify the scene BEFORE
                # deciding, and only DUMPING scenes can trigger.
                scene = getattr(report, "scene_type", "").upper().strip()
                if scene != "DUMPING" and report.new_litter_detected:
                    logger.info(
                        "gate override: scene_type=%s but new_litter_detected=true -> forcing false (request_id=%s)",
                        scene, request_id,
                    )
                    report.new_litter_detected = False
                    report.confidence_0_100 = 0

                usage = _extract_usage(response)
                latency_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    json.dumps(
                        {
                            "event": "gemini_new_litter_gate_ok",
                            "request_id": request_id,
                            "model": model_name,
                            "latency_ms": latency_ms,
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "total_tokens": usage.total_tokens,
                            "first_frame": first_frame.name,
                            "last_frame": last_frame.name,
                        },
                        ensure_ascii=False,
                    )
                )
                return GeminiNewLitterInferenceResult(
                    report=report,
                    usage=usage,
                    latency_ms=latency_ms,
                    model=model_name,
                    raw_json=raw_text,
                )
            except FutureTimeoutError:
                last_error = TimeoutError(f"Gemini gate timeout after {timeout_s}s")
                logger.warning(
                    "gemini gate timeout request_id=%s attempt=%d/%d",
                    request_id,
                    attempt,
                    attempts,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "gemini gate error request_id=%s attempt=%d/%d error=%s",
                    request_id,
                    attempt,
                    attempts,
                    exc,
                )
            if attempt < attempts:
                backoff_s = min(2 ** (attempt - 1), 10)
                time.sleep(backoff_s)

        raise RuntimeError(f"Gemini new-litter gate failed after {attempts} attempts: {last_error}") from last_error
    finally:
        if mosaic_temp is not None:
            try:
                mosaic_temp.unlink(missing_ok=True)
            except OSError:
                pass
