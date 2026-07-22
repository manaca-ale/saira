"""Gemini structured inference adapter for SAIRA worker."""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import time
import unicodedata
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

from pydantic import ValidationError

from . import config
from . import _prompts_audit, _prompts_g3, _prompts_v2, _prompts_v3
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

# Chaves SEM acento: normalize_offender_types remove diacriticos antes do lookup
# (o modelo responde "carroça"/"caminhão" e antes disso os tokens acentuados
# caiam fora do mapa e eram descartados em silencio).
OFFENDER_TYPE_MAP = {
    "pessoa": "Pessoa",
    "pessoas": "Pessoa",
    "person": "Pessoa",
    "people": "Pessoa",
    "pedestre": "Pessoa",
    "pedestrian": "Pessoa",
    "carro": "Carro",
    "car": "Carro",
    "van": "Carro",
    "pickup": "Carro",
    "caminhonete": "Carro",
    "onibus": "Carro",
    "bus": "Carro",
    "caminhao": "Caminhao",
    "truck": "Caminhao",
    "cacamba": "Caminhao",
    "moto": "Moto",
    "motorcycle": "Moto",
    "bike": "Outro",
    "bicicleta": "Outro",
    "bicycle": "Outro",
    "carroca": "Carroca",
    "cart": "Carroca",
    "handcart": "Carroca",
    "wheelbarrow": "Carroca",
    "carrinho": "Carroca",
    "carrinho de mao": "Carroca",
}

SYSTEM_PROMPT = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos estacionados,
infraestrutura municipal fixa (postes, lixeiras com tampa, bollards, marcacoes viarias),
PILHAS DE LIXO PRE-EXISTENTES de janelas anteriores, e iluminacao natural variavel.
Estes elementos sao NORMAIS e ESPERADOS — uma pilha que ja estava no primeiro frame
e PERMANECE inalterada no ultimo frame NAO e infracao.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos/permanentes visiveis no primeiro frame.
2. DELTA TEMPORAL: Identifique o que MUDOU entre o primeiro e o ultimo frame.
3. CLASSIFICACAO: Cada mudanca e SOMBRA_ILUMINACAO, OBJETO_EM_MOVIMENTO, ou COMPORTAMENTO_DESCARTE.
4. DECISAO: infraction_confirmed=true quando houver COMPORTAMENTO_DESCARTE confirmado.

COMPORTAMENTO_DESCARTE e confirmado quando QUALQUER das seguintes evidencias e visivel:
A) Material novo claramente visivel no chao que surgiu durante a sequencia.
B) Veiculo PARADO (mesma posicao em 2+ frames) proximo a area de residuos com pessoa
   ESTACIONARIA entre o veiculo e o chao, carregando ou manuseando material.
C) Veiculo com cacamba aberta/levantada proximo a pilha de residuos, descarregando.

SINAL-CHAVE: Veiculos e pessoas realizando descarte ficam ESTACIONARIOS entre os frames
(mesma posicao relativa). Trafego normal mostra veiculos/pessoas em POSICOES DIFERENTES
entre frames. Use esta diferenca para distinguir descarte de trafego.

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000 [y_min, x_min, y_max, x_max]:
- waste_bbox: delimitando o residuo depositado (quando visivel como objeto distinto)
- offender_bbox: delimitando o infrator/veiculo (quando visivel)
Quando o material depositado se mistura a uma pilha existente, waste_bbox pode ser null
desde que offender_bbox identifique o agente do descarte.

Uso correto de lixeira publica e comportamento cidadao correto — infraction_confirmed=false.
Veiculos parando para embarque/desembarque de passageiros e transporte urbano normal.
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_detected descreve somente a capacidade de identificar o autor/veiculo.
Se um campo nao puder ser inferido com seguranca, retorne null.
""".strip()

NEW_LITTER_SYSTEM_PROMPT = """
You analyze CCTV frames to classify urban scenes. You receive 2-5 frames from the same camera.

FIRST, classify scene_type as one of:
- EMPTY: No vehicles or people visible in any frame.
- TRAFFIC: Vehicles and/or people moving through the scene (different positions across frames).
- PARKED: Vehicles stationary but NO person handling material nearby.
- DUMPING: A vehicle is STOPPED and a person is ACTIVELY depositing material on the ground.

IMPORTANT: Over 95% of scenes are EMPTY, TRAFFIC, or PARKED. Default to these.

EVALUATE each boolean field INDEPENDENTLY based on visual evidence:
- vehicle_stopped: Is a vehicle stationary (same position in 2+ frames)?
- person_handling_material: Is a person carrying, unloading, or depositing material near a vehicle?
- new_ground_material: Is there new material on the ground in the last frame that was absent in the first?

COMMON SCENES (these are normal, not DUMPING):
- Vehicles driving through = TRAFFIC
- Vehicle stopped briefly for passenger pickup/dropoff (person enters/exits vehicle) = TRAFFIC
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
        "Return JSON: scene_type, vehicle_stopped, person_handling_material, "
        "new_ground_material, new_litter_detected, confidence_0_100, evidence_summary, "
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
    # V2 fields (default False/none for backwards compatibility with current prompts).
    is_maintenance: bool = False
    prompt_version: str = "current"


@dataclass
class ModelOverride:
    """Overrides por-chamada (usado só pelo shadow — prod passa None e nada muda).
    Roteia a chamada para um modelo/cliente/config diferentes, mantendo TODO o
    pós-processamento dos wrappers (paridade com o benchmark)."""
    model: Optional[str] = None
    thinking_level: Optional[str] = None          # Gemini-3: "low"|"medium"|"high"
    media_resolution: Optional[str] = None        # "low"|"medium"|"high"
    max_output_tokens: Optional[int] = None
    client: object = None                          # cliente genai dedicado


_client = None


def _get_client():
    global _client
    if genai is None:
        raise RuntimeError(
            "google-genai package is not available. Install dependencies from requirements.txt."
        )
    if _client is None:
        if getattr(config, "GEMINI_USE_VERTEX", False):
            _client = genai.Client(
                vertexai=True,
                project=config.GCP_PROJECT,
                location=config.GCP_LOCATION,
            )
        elif config.GEMINI_API_KEY:
            _client = genai.Client(api_key=config.GEMINI_API_KEY)
        else:
            raise RuntimeError(
                "GEMINI_API_KEY is required when AI_MODE is shadow or gemini "
                "(or set GEMINI_USE_VERTEX=true)"
            )
    return _client


_fallback_client = None


def _get_fallback_client():
    """Lazy Vertex client pinned to GCP_LOCATION_FALLBACK, used only when the
    primary location returns 429. Returns None when disabled (not Vertex, no
    fallback region set, or fallback == primary)."""
    global _fallback_client
    if genai is None or not getattr(config, "GEMINI_USE_VERTEX", False):
        return None
    fb_loc = (getattr(config, "GCP_LOCATION_FALLBACK", "") or "").strip()
    if not fb_loc or fb_loc == config.GCP_LOCATION:
        return None
    if _fallback_client is None:
        _fallback_client = genai.Client(
            vertexai=True,
            project=config.GCP_PROJECT,
            location=fb_loc,
        )
    return _fallback_client


_shadow_client = None


def _get_shadow_client():
    """Cliente DEDICADO do shadow (projeto GCP próprio) para isolar o custo/quota.
    Prioridade: SHADOW_GEMINI_API_KEY (AI Studio) → Vertex no SHADOW_GCP_PROJECT.
    Retorna None se nada configurado (o caller deve pular o shadow)."""
    global _shadow_client
    if genai is None:
        return None
    if _shadow_client is None:
        key = (getattr(config, "SHADOW_GEMINI_API_KEY", "") or "").strip()
        proj = (getattr(config, "SHADOW_GCP_PROJECT", "") or "").strip()
        if key:
            _shadow_client = genai.Client(api_key=key)
        elif proj:
            _shadow_client = genai.Client(
                vertexai=True, project=proj,
                location=(getattr(config, "SHADOW_GCP_LOCATION", "") or "global"))
        else:
            return None
    return _shadow_client


def _is_resource_exhausted(exc: Exception) -> bool:
    """True when a Gemini call failed with 429 / RESOURCE_EXHAUSTED (quota /
    Dynamic Shared Quota congestion) — the case worth retrying on another region."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code == 429:
        return True
    return "RESOURCE_EXHAUSTED" in str(exc).upper()


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


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_offender_types(values: Optional[list[str]]) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    dropped: list[str] = []
    for value in values:
        key = _strip_accents(str(value).strip().lower())
        mapped = OFFENDER_TYPE_MAP.get(key)
        if mapped:
            if mapped not in normalized:
                normalized.append(mapped)
        elif key:
            dropped.append(key)
    if dropped:
        # Token fora do mapa vira lacuna silenciosa na taxonomia — logar para
        # que a proxima categoria faltante apareça, em vez de sumir.
        logger.info(json.dumps({"event": "offender_type_unmapped", "tokens": dropped}))
    return normalized


def _build_generate_config(schema: dict, max_output_tokens: Optional[int] = None,
                           thinking_budget: Optional[int] = None, seed: Optional[int] = None,
                           thinking_level: Optional[str] = None,
                           media_resolution: Optional[str] = None):
    # The SDK supports response_schema for structured outputs.
    if types is None:
        raise RuntimeError("google-genai types are unavailable")
    # thinking_level (Gemini-3 nativo: "low"|"medium"|"high") tem precedência sobre o
    # thinking_budget (estilo 2.5); só um é enviado.
    thinking_config = None
    if thinking_level:
        thinking_config = types.ThinkingConfig(thinking_level=thinking_level)
    elif thinking_budget is not None:
        thinking_config = types.ThinkingConfig(thinking_budget=thinking_budget)
    cfg = types.GenerateContentConfig(
        temperature=config.GEMINI_TEMPERATURE,
        max_output_tokens=max_output_tokens or config.GEMINI_MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=thinking_config,
        seed=seed,
    )
    if media_resolution:
        cfg.media_resolution = getattr(
            types.MediaResolution, f"MEDIA_RESOLUTION_{media_resolution.upper()}")
    return cfg


def _call_model(
    image_paths: list[Path],
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    response_schema: dict,
    max_output_tokens: Optional[int] = None,
    thinking_budget: Optional[int] = None,
    seed: Optional[int] = None,
    thinking_level: Optional[str] = None,
    media_resolution: Optional[str] = None,
    client=None,
):
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

    gen_config = _build_generate_config(
        response_schema, max_output_tokens=max_output_tokens,
        thinking_budget=thinking_budget, seed=seed,
        thinking_level=thinking_level, media_resolution=media_resolution,
    )

    def _invoke(cl):
        return cl.models.generate_content(
            model=model_name, contents=contents, config=gen_config,
        )

    # `client` explícito (ex.: cliente dedicado do shadow) NÃO usa o fallback de região
    # de prod — mantém o custo/quota 100% no projeto do shadow.
    if client is not None:
        return _invoke(client)

    try:
        return _invoke(_get_client())
    except Exception as exc:  # noqa: BLE001
        fb = _get_fallback_client()
        if fb is not None and _is_resource_exhausted(exc):
            logger.warning(
                "gemini %s exhausted (%s) — retrying on fallback region %s",
                config.GCP_LOCATION, type(exc).__name__, config.GCP_LOCATION_FALLBACK,
            )
            return _invoke(fb)
        raise


# Preços por modelo (USD por 1M tokens) — (input, output). A taxa de output
# também se aplica aos tokens de THINKING. Fallback = config (preço único legado).
_MODEL_PRICES = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.125, 0.75),
}


def _price_key(model_name: str) -> str:
    """Normaliza nomes versionados (ex.: gemini-2.5-flash-002) para a chave de preço."""
    m = (model_name or "").strip().lower()
    if "flash-lite" in m:
        # Gemini-3.x flash-lite tem preço próprio; senão cai no 2.5.
        if "gemini-3" in m or "-3." in m or "3.1" in m:
            return "gemini-3.1-flash-lite"
        return "gemini-2.5-flash-lite"
    if "flash" in m:
        return "gemini-2.5-flash"
    return ""


def _extract_usage(resp, model_name: str = "") -> GeminiUsage:
    metadata = getattr(resp, "usage_metadata", None)
    if not metadata:
        return GeminiUsage()

    input_tokens = int(getattr(metadata, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(metadata, "candidates_token_count", 0) or 0)
    # Tokens de "thinking": faturados na taxa de OUTPUT mas NÃO vêm em
    # candidates_token_count. Sem contá-los, o custo do detail (flash + thinking)
    # era subestimado em ~10x.
    thinking_tokens = int(getattr(metadata, "thoughts_token_count", 0) or 0)
    total_tokens = int(
        getattr(metadata, "total_token_count", 0)
        or (input_tokens + output_tokens + thinking_tokens)
    )

    in_price, out_price = _MODEL_PRICES.get(
        _price_key(model_name),
        (config.GEMINI_INPUT_TOKEN_PRICE_PER_1M, config.GEMINI_OUTPUT_TOKEN_PRICE_PER_1M),
    )
    estimated_cost = (
        (input_tokens / 1_000_000.0) * in_price
        + ((output_tokens + thinking_tokens) / 1_000_000.0) * out_price
    )

    return GeminiUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_tokens=thinking_tokens,
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


def _parse_report_lenient(schema_cls, raw_text: str):
    """Validate JSON against a Pydantic schema, tolerating over-long string fields.

    Flash-Lite is non-deterministic and on rich/real dumping scenes it occasionally
    overruns a `max_length` text field (e.g. `evidence_summary` >500 chars). Plain
    `model_validate_json` would then raise `string_too_long`, and after retries the
    whole gate call fails with RuntimeError — i.e. a REAL descarte gets dropped on a
    cosmetic field. Here we clip the offending fields to their schema maxLength and
    re-validate, preserving the actual decision (scene_type/new_litter_detected/etc).
    """
    try:
        return schema_cls.model_validate_json(raw_text)
    except ValidationError as exc:
        errs = exc.errors()
        if not any(e.get("type") == "string_too_long" for e in errs):
            raise
        data = json.loads(raw_text)
        props = schema_cls.model_json_schema().get("properties", {})
        limits = {k: v["maxLength"] for k, v in props.items() if "maxLength" in v}
        for e in errs:
            loc = e.get("loc") or ()
            if e.get("type") == "string_too_long" and loc:
                key = loc[0]
                if key in limits and isinstance(data.get(key), str):
                    data[key] = data[key][: limits[key]]
        return schema_cls.model_validate(data)


def _validate_bbox(bbox: object, label: str) -> Optional[list[int]]:
    """Validate a Gemini bounding box [y_min, x_min, y_max, x_max] normalized 0-1000.

    Returns None if invalid (wrong length, out of range, too large, or too small).
    """
    if bbox is None:
        return None
    try:
        coords = [int(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    if len(coords) != 4:
        return None
    y_min, x_min, y_max, x_max = coords
    if not all(0 <= v <= 1000 for v in coords):
        return None
    if y_max <= y_min or x_max <= x_min:
        return None
    area = (y_max - y_min) * (x_max - x_min)
    total_area = 1000 * 1000
    ratio = area / total_area
    if ratio > 0.60:
        logger.info("bbox_rejected_%s: covers %.1f%% of image (too large)", label, ratio * 100)
        return None
    if ratio < 0.01:
        logger.info("bbox_rejected_%s: covers %.2f%% of image (too small)", label, ratio * 100)
        return None
    return coords


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

    # Visual grounding — validate bounding boxes and reject ungrounded claims.
    report.waste_bbox = _validate_bbox(getattr(report, "waste_bbox", None), "waste")
    report.offender_bbox = _validate_bbox(getattr(report, "offender_bbox", None), "offender")

    # Visual grounding: require at least ONE valid bbox (waste OR offender).
    # When waste is deposited on an existing pile, waste_bbox may be null but
    # offender_bbox (vehicle/person) still provides spatial accountability.
    has_grounding = report.waste_bbox is not None or report.offender_bbox is not None
    if config.GEMINI_REQUIRE_BBOX and report.infraction_confirmed and not has_grounding:
        logger.info(
            "grounding_rejection: infraction_confirmed=true but no valid bbox "
            "(waste_bbox=%s, offender_bbox=%s) -> forcing false",
            report.waste_bbox, report.offender_bbox,
        )
        report.infraction_confirmed = False
        report.confidence_0_100 = 0

    return report


def _build_mangabeira_pilecrops_user_prompt(
    camera_context: Optional[dict[str, str]] = None,
    *,
    frame_names: Optional[list[str]] = None,
    crop_count: int = 0,
    prior_window_context: Optional[str] = None,
) -> str:
    """User prompt for the MANGABEIRA+pile-crops detail call.

    Tells the model the input has TWO sequences: N global frames followed by
    M hi-res pile-zone crops (upscale 2x). The system prompt
    (DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS) handles the decision logic;
    this just labels the input.
    """
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if value:
                context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    n_global = len(frame_names or [])
    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens e retorne JSON estruturado conforme schema.\n"
        f"\nESTRUTURA DO INPUT (em ordem):\n"
        f"- SEQUENCIA 1: {n_global} FRAMES GLOBAIS da camera (ordem cronologica, "
        f"primeiro=earliest, ultimo=latest).\n"
        f"- SEQUENCIA 2: {crop_count} CROPS ALTA-RES (upscale 2x) da pile-zone, "
        f"amostrados uniformemente da MESMA janela temporal.\n"
        "Use ambas sequencias conforme o system prompt. event_frame_name e "
        "offender_frame_name devem ser escolhidos dentre os nomes da SEQUENCIA 1.\n"
        f"Nomes de frame permitidos (SEQUENCIA 1): {frame_block}\n"
        f"{prior_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )


def analyze_with_gemini(
    image_paths: list[Path],
    camera_context: Optional[dict[str, str]] = None,
    request_id: Optional[str] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
    prompt_version: str = "current",
    pile_crops: Optional[list[Path]] = None,
    override: "Optional[ModelOverride]" = None,
) -> GeminiInferenceResult:
    """Run Gemini inference with retry/timeout and strict schema validation.

    Args:
        mosaic_mode: "off" sends frames individually; "4x3" composes a single 4×3
            grid image; "3x2split" composes two 3×2 grid images.
        prompt_version: "current" (default), "v2", "v3", "audit", "audit_v2", or
            "mangabeira_with_pilecrops".
            - V2 uses the behavioral anti-collection prompt.
            - V3 uses posture-first signals.
            - audit treats Agent-2 as an adversarial reviewer of the gate,
              requiring `fp_pattern_match` enum to classify the scene and
              rejecting infraction_confirmed when pattern != real_dumping.
            - audit_v2 relaxes the V1 audit: drops the 4-question hard rule
              and force-falses only for 5 unambiguous FP patterns
              (traffic_passing, municipal_collection, pruning_crew,
              rain_blur, parking_dropoff). carroceiro_sorting / other /
              real_dumping are left to the model's judgement.
            - mangabeira_with_pilecrops: per-camera (esp32_002 only),
              negative-first prompt with pile-zone hi-res crops augmentation.
              Requires `pile_crops` argument with N upscaled crop paths.
              Campaign 24 winner for recall on cam_11 (91.7% single-call).
        pile_crops: Optional list of hi-res pile-zone crop paths to send
            alongside `image_paths` when prompt_version="mangabeira_with_pilecrops".
            Ignored for other prompt versions (kept for backward compat).
    """
    use_mangabeira_crops = prompt_version == "mangabeira_with_pilecrops"
    use_audit_v2 = prompt_version == "audit_v2"
    use_audit = prompt_version == "audit"
    use_v3 = prompt_version == "v3"
    use_v2 = prompt_version == "v2"
    use_g3 = prompt_version == "g3"
    if use_g3:
        # Gemini-3 recall-first (campanha 47); mesmo schema/pós-proc do "current".
        system_prompt = _prompts_g3.G3_DETAIL_PROMPT
        schema_cls = GeminiInfractionReport
    elif use_mangabeira_crops:
        # Per-camera detail prompt selected by device_id; crops mandatory.
        system_prompt = _prompts_v3.detail_system_prompt_for_camera(
            camera_context, has_pilecrops=True,
        )
        schema_cls = GeminiInfractionReport
    elif use_audit_v2:
        system_prompt = _prompts_audit.SYSTEM_PROMPT_AUDIT_V2
        schema_cls = _prompts_audit.GeminiInfractionReportAudit
    elif use_audit:
        system_prompt = _prompts_audit.SYSTEM_PROMPT_AUDIT
        schema_cls = _prompts_audit.GeminiInfractionReportAudit
    elif use_v3:
        system_prompt = _prompts_v3.SYSTEM_PROMPT_V3
        schema_cls = GeminiInfractionReport
    elif use_v2:
        system_prompt = _prompts_v2.SYSTEM_PROMPT_V2
        schema_cls = GeminiInfractionReport
    else:
        system_prompt = SYSTEM_PROMPT
        schema_cls = GeminiInfractionReport

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

    # MANGABEIRA + pile-crops: append hi-res crops AFTER globals. The prompt
    # text explains the structure (sequencia 1 = globais, sequencia 2 = crops).
    if use_mangabeira_crops and pile_crops:
        send_paths = list(send_paths) + list(pile_crops)

    attempts = max(0, config.GEMINI_MAX_RETRIES) + 1
    last_error: Optional[Exception] = None

    try:
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                if use_audit_v2:
                    user_prompt_text = _prompts_audit.build_audit_v2_user_prompt(
                        camera_context, frame_names=frame_names,
                        mosaic_mode=mosaic_mode, prior_window_context=prior_window_context,
                    )
                elif use_audit:
                    user_prompt_text = _prompts_audit.build_audit_user_prompt(
                        camera_context, frame_names=frame_names,
                        mosaic_mode=mosaic_mode, prior_window_context=prior_window_context,
                    )
                elif use_mangabeira_crops:
                    user_prompt_text = _build_mangabeira_pilecrops_user_prompt(
                        camera_context,
                        frame_names=frame_names,
                        crop_count=len(pile_crops) if pile_crops else 0,
                        prior_window_context=prior_window_context,
                    )
                elif use_v3:
                    user_prompt_text = _prompts_v3.build_v3_user_prompt_detail(
                        camera_context, frame_names=frame_names,
                        mosaic_mode=mosaic_mode, prior_window_context=prior_window_context,
                    )
                elif use_v2:
                    user_prompt_text = _prompts_v2.build_v2_user_prompt_detail(
                        camera_context, frame_names=frame_names,
                        mosaic_mode=mosaic_mode, prior_window_context=prior_window_context,
                    )
                else:
                    user_prompt_text = _user_prompt(
                        camera_context, frame_names=frame_names,
                        mosaic_mode=mosaic_mode, prior_window_context=prior_window_context,
                    )

                _detail_model = (override.model if override and override.model
                                 else config.GEMINI_MODEL)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        _call_model,
                        send_paths,
                        system_prompt,
                        user_prompt_text,
                        _detail_model,
                        schema_cls.model_json_schema(),
                        (override.max_output_tokens if override and override.max_output_tokens
                         else None),
                        thinking_level=(override.thinking_level if override else None),
                        media_resolution=(override.media_resolution if override else None),
                        client=(override.client if override else None),
                    )
                    response = fut.result(timeout=max(1, config.GEMINI_TIMEOUT_SECONDS))

                raw_text = _extract_text(response)
                report = schema_cls.model_validate_json(raw_text)
                report = _sanitize_report(report, allowed_frame_names=allowed_frame_names)
                if use_audit_v2:
                    report = _prompts_audit.apply_audit_v2_consistency(report, request_id=request_id)
                elif use_audit:
                    report = _prompts_audit.apply_audit_consistency(report, request_id=request_id)

                usage = _extract_usage(response, _detail_model)
                latency_ms = int((time.monotonic() - started) * 1000)

                logger.info(
                    json.dumps(
                        {
                            "event": "gemini_inference_ok",
                            "request_id": request_id,
                            "model": _detail_model,
                            "latency_ms": latency_ms,
                            "input_tokens": usage.input_tokens,
                            "output_tokens": usage.output_tokens,
                            "thinking_tokens": usage.thinking_tokens,
                            "total_tokens": usage.total_tokens,
                        },
                        ensure_ascii=False,
                    )
                )

                return GeminiInferenceResult(
                    report=report,
                    usage=usage,
                    latency_ms=latency_ms,
                    model=_detail_model,
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
    prompt_version: str = "current",
    override: "Optional[ModelOverride]" = None,
) -> GeminiNewLitterInferenceResult:
    """Stage-1 gate: compare first and last frame for new litter appearance.

    Args:
        use_mosaic: when True, composes a 2x1 side-by-side image before sending.
        mid_frames: optional list of mid-window frames (e.g. at 25%/50%/75%) to detect
            ghost events (arrive-dump-leave within window).
        prompt_version: "current" (V1), "v2" (behavioral discriminators, _prompts_v2.py),
            "v3" (posture-first signals, _prompts_v3.py), or "g3" (Gemini-3 recall-first,
            _prompts_g3.py; usa o schema/pós-processamento V1).
        override: ModelOverride (só shadow) — modelo/cliente/media_resolution/thinking_level
            alternativos; None = comportamento de prod.
    """
    attempts = max(0, config.GEMINI_MAX_RETRIES) + 1
    last_error: Optional[Exception] = None
    model_name = (override.model if override and override.model
                  else (config.GEMINI_AGENT1_MODEL or config.GEMINI_MODEL))
    timeout_s = max(1, config.GEMINI_AGENT1_TIMEOUT_SECONDS)

    camera_device_id = ""
    if camera_context:
        camera_device_id = str(camera_context.get("device_id") or "").strip().lower()
    # g3 NÃO usa o gate V3 per-câmera (é Gemini-3 com prompt próprio + pós-proc V1).
    use_g3 = prompt_version == "g3"
    use_camera_v3_gate = (not use_g3) and camera_device_id in ("esp32_002", "esp32_001")
    use_v3 = (not use_g3) and (prompt_version == "v3" or use_camera_v3_gate)
    use_v2 = (not use_g3) and prompt_version == "v2"
    if use_v3:
        system_prompt = _prompts_v3.gate_system_prompt_for_camera(camera_context)
        schema_cls = _prompts_v3.GeminiNewLitterReportV3
    elif use_v2:
        system_prompt = _prompts_v2.NEW_LITTER_SYSTEM_PROMPT_V2
        schema_cls = _prompts_v2.GeminiNewLitterReportV2
    elif use_g3:
        system_prompt = _prompts_g3.G3_GATE_PROMPT
        schema_cls = GeminiNewLitterReport
    else:
        system_prompt = NEW_LITTER_SYSTEM_PROMPT
        schema_cls = GeminiNewLitterReport

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

    if use_v3:
        user_prompt_text = _prompts_v3.build_v3_user_prompt_gate(
            first_frame.name, last_frame.name, camera_context,
            prior_window_context=prior_window_context, mosaic=use_mosaic,
            mid_frame_names=mid_frame_names,
        )
    elif use_v2:
        user_prompt_text = _prompts_v2.build_v2_user_prompt_gate(
            first_frame.name, last_frame.name, camera_context,
            prior_window_context=prior_window_context, mosaic=use_mosaic,
            mid_frame_names=mid_frame_names,
        )
    else:
        user_prompt_text = _new_litter_user_prompt(
            first_frame.name, last_frame.name, camera_context,
            prior_window_context=prior_window_context, mosaic=use_mosaic,
            mid_frame_names=mid_frame_names,
        )

    try:
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(
                        _call_model,
                        image_paths,
                        system_prompt,
                        user_prompt_text,
                        model_name,
                        schema_cls.model_json_schema(),
                        (override.max_output_tokens if override and override.max_output_tokens
                         else config.GEMINI_AGENT1_MAX_OUTPUT_TOKENS),
                        thinking_budget=(None if override and override.thinking_level
                                         else config.GEMINI_AGENT1_THINKING_BUDGET),
                        seed=42,
                        thinking_level=(override.thinking_level if override else None),
                        media_resolution=(override.media_resolution if override else None),
                        client=(override.client if override else None),
                    )
                    response = fut.result(timeout=timeout_s)

                raw_text = _extract_text(response)
                report = _parse_report_lenient(schema_cls, raw_text)
                report.waste_type = normalize_waste_type(report.waste_type)
                report.confidence_0_100 = max(0, min(100, int(report.confidence_0_100)))

                is_maintenance = False
                if use_v3:
                    # V3 posture-first gate (handles invisible pedestrian dumping).
                    report, is_maintenance = _prompts_v3.apply_v3_gates(report, request_id=request_id)
                elif use_v2:
                    # V2 behavioral gate (signals + uniform-independent override).
                    report, is_maintenance = _prompts_v2.apply_v2_gates(report, request_id=request_id)
                else:
                    # V1 original gate (scene + 2-of-3 booleans).
                    scene = getattr(report, "scene_type", "").upper().strip()
                    if scene != "DUMPING" and report.new_litter_detected:
                        logger.info(
                            "gate override: scene_type=%s but new_litter_detected=true -> forcing false (request_id=%s)",
                            scene, request_id,
                        )
                        report.new_litter_detected = False
                        report.confidence_0_100 = 0

                    bool_count = sum([
                        bool(getattr(report, "vehicle_stopped", False)),
                        bool(getattr(report, "person_handling_material", False)),
                        bool(getattr(report, "new_ground_material", False)),
                    ])
                    if report.new_litter_detected and bool_count < 2:
                        logger.info(
                            "deterministic_gate: only %d/3 conditions met "
                            "(vehicle_stopped=%s, person_handling=%s, new_ground=%s) "
                            "-> forcing false (request_id=%s)",
                            bool_count,
                            getattr(report, "vehicle_stopped", False),
                            getattr(report, "person_handling_material", False),
                            getattr(report, "new_ground_material", False),
                            request_id,
                        )
                        report.new_litter_detected = False
                        report.confidence_0_100 = 0

                    if not report.new_litter_detected and scene == "DUMPING" and bool_count >= 2:
                        logger.info(
                            "positive_override: scene=DUMPING + %d/3 conditions met "
                            "-> forcing new_litter_detected=true (request_id=%s)",
                            bool_count, request_id,
                        )
                        report.new_litter_detected = True
                        report.confidence_0_100 = max(report.confidence_0_100, 85)

                usage = _extract_usage(response, model_name)
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
                            "thinking_tokens": usage.thinking_tokens,
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
                    is_maintenance=is_maintenance,
                    prompt_version=prompt_version,
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
