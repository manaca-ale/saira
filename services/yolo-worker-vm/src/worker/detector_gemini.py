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
from .schemas_gemini import GeminiInfractionReport, GeminiNewLitterReport

logger = logging.getLogger(__name__)

LEGACY_PLATE_RE = re.compile(r"^[A-Z]{3}-?\d{4}$")
MERCOSUL_PLATE_RE = re.compile(r"^[A-Z]{3}\d[A-Z]\d{2}$")

WASTE_TYPE_MAP = {
    "entulho": "Entulho",
    "construcao": "Entulho",
    "debris": "Entulho",
    "lixo domiciliar": "Lixo domiciliar",
    "domestic waste": "Lixo domiciliar",
    "household waste": "Lixo domiciliar",
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
infraction_confirmed deve ser TRUE somente quando houver evidencia de descarte NOVO depositado durante a sequencia, mesmo sem identificar o infrator.
offender_detected descreve somente a capacidade de identificar o autor/veiculo e NAO invalida a infracao.
Se um campo nao puder ser inferido com seguranca, retorne null no campo.
""".strip()

NEW_LITTER_SYSTEM_PROMPT = """
You are a visual auditor specialized in comparing two CCTV frames (start and end of a time window).
Your task is to detect whether SOLID WASTE appeared or increased in the final frame due to illegal dumping.

MANDATORY STEP before deciding (be CONCISE: max 5 items per list):
Fill scene_delta_analysis with:
  (1) FIXED and INANIMATE objects visible in the initial frame (do NOT list vehicles, people, or animals),
  (2) FIXED and INANIMATE objects visible in the final frame — INCLUDING objects left behind by people
      (bags, boxes, rubble, furniture) but do NOT list the people, vehicles, or animals themselves,
  (3) each difference classified as: SHADOW | LIGHTING | PUDDLE | MOVING_OBJECT | NEW_SOLID_WASTE | EXISTING_WASTE_SHIFTED.

DECISION RULE:
- new_litter_detected=true ONLY if there is a difference classified as NEW_SOLID_WASTE.
- NEW_SOLID_WASTE is abandoned solid waste: bag, rubble, furniture, electronics, household waste, boxes left on the ground.
- Vehicles (cars, motorcycles, buses, bicycles) and people themselves are NEVER NEW_SOLID_WASTE, even if they appear in the final frame.
- Shadows have diffuse edges. Solid waste has well-defined material boundaries.
- Reflections, puddles, lighting changes, and compression artifacts are NOT NEW_SOLID_WASTE.
- Objects ALREADY present in the initial frame that remain in the final frame are EXISTING_WASTE_SHIFTED, not NEW_SOLID_WASTE.

Respond with ONLY valid JSON with the requested fields.
""".strip()


def _user_prompt(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
) -> str:
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if value:
                context_lines.append(f"- {key}: {value}")

    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"
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
        "Contexto da camera:\n"
        f"{context_block}"
    )


def _new_litter_user_prompt(
    first_frame_name: str,
    last_frame_name: str,
    camera_context: Optional[dict[str, str]] = None,
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

    return (
        "Compare ONLY two frames: start and end of the window.\n"
        f"Initial frame: {first_frame_name}\n"
        f"Final frame: {last_frame_name}\n"
        "Follow the MANDATORY STEP: fill scene_delta_analysis classifying each difference "
        "before setting new_litter_detected.\n"
        "Return JSON with all fields: scene_delta_analysis, new_litter_detected, "
        "confidence_0_100, evidence_summary, first_frame_has_litter, last_frame_has_litter, "
        "waste_type, raw_reason_codes.\n"
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


def _build_generate_config(schema: dict, max_output_tokens: Optional[int] = None):
    # The SDK supports response_schema for structured outputs.
    if types is None:
        raise RuntimeError("google-genai types are unavailable")
    return types.GenerateContentConfig(
        temperature=config.GEMINI_TEMPERATURE,
        max_output_tokens=max_output_tokens or config.GEMINI_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_schema=schema,
    )


def _call_model(
    image_paths: list[Path],
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    response_schema: dict,
    max_output_tokens: Optional[int] = None,
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
        config=_build_generate_config(response_schema, max_output_tokens=max_output_tokens),
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
) -> GeminiInferenceResult:
    """Run Gemini inference with retry/timeout and strict schema validation."""

    if not image_paths:
        raise ValueError("image_paths must contain at least one frame")
    frame_names = [p.name for p in image_paths]
    allowed_frame_names = set(frame_names)

    attempts = max(0, config.GEMINI_MAX_RETRIES) + 1
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(
                    _call_model,
                    image_paths,
                    SYSTEM_PROMPT,
                    _user_prompt(camera_context, frame_names=frame_names),
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


def analyze_new_litter_with_gemini(
    first_frame: Path,
    last_frame: Path,
    camera_context: Optional[dict[str, str]] = None,
    request_id: Optional[str] = None,
    prior_window_context: Optional[str] = None,
) -> GeminiNewLitterInferenceResult:
    """Stage-1 gate: compare first and last frame for new litter appearance."""
    attempts = max(0, config.GEMINI_MAX_RETRIES) + 1
    last_error: Optional[Exception] = None
    image_paths = [first_frame, last_frame]
    model_name = config.GEMINI_AGENT1_MODEL or config.GEMINI_MODEL
    timeout_s = max(1, config.GEMINI_AGENT1_TIMEOUT_SECONDS)

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
                    ),
                    model_name,
                    GeminiNewLitterReport.model_json_schema(),
                    config.GEMINI_AGENT1_MAX_OUTPUT_TOKENS,
                )
                response = fut.result(timeout=timeout_s)

            raw_text = _extract_text(response)
            report = GeminiNewLitterReport.model_validate_json(raw_text)
            report.waste_type = normalize_waste_type(report.waste_type)
            report.confidence_0_100 = max(0, min(100, int(report.confidence_0_100)))

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
