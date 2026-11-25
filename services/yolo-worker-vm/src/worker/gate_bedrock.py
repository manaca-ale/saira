"""Gate (Agent-1) no AWS Bedrock — finalista A da campanha 54 (Amazon Nova Lite).

Mesma medida do braço `nvl_v1p_low_ctx` de
`benchmarks/campaigns/54-*/scripts/run_gate54_bedrock.py`: os frames do gate reduzidos a
640 px (o análogo do `media_resolution=low`), o prompt de sistema V1 na variante `v1p`,
o MESMO texto de usuário do gate Gemini (com o aviso da janela anterior), o esquema
`GeminiNewLitterReport` pedido como JSON em texto e a pós-regra V1 (cena DUMPING + 2 de
3 sinais). Devolve o mesmo `GeminiNewLitterInferenceResult` do gate Gemini, então o
resto da cascata não muda.

Desligado por padrão (`GATE_BEDROCK_ENABLED=false`, lista `GATE_BEDROCK_DEVICES`).
Qualquer falha levanta `BedrockGateError`; quem chama (`main._run_gate`) cai no gate
Gemini configurado, para a janela não se perder. Disjuntor próprio: após N falhas
seguidas, o Bedrock é pulado por um tempo e o gate Gemini assume direto.

O Nova Lite só foi medido ATRÁS do filtro (`gate_prefilter`); sem o filtro ele dispara
demais em cena vazia. Mandar imagens para a AWS é decisão de contrato, não de engenharia.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from . import config
from . import detector_bedrock
from . import detector_gemini as dg
from ._shadow_gate51 import apply_v1_gate
from .models import GeminiUsage
from .schemas_gemini import GeminiNewLitterReport

logger = logging.getLogger(__name__)

_BREAKER = {"fails": 0, "open_until": 0.0}


class BedrockGateError(RuntimeError):
    """O gate no Bedrock não devolveu um relatório válido (ou está com o disjuntor aberto)."""


def enabled_for(device_id: Optional[str]) -> bool:
    return bool(config.GATE_BEDROCK_ENABLED
                and (device_id or "").strip().lower() in config.GATE_BEDROCK_DEVICES)


def model_id() -> str:
    spec = detector_bedrock.MODELS.get(config.GATE_BEDROCK_ALIAS)
    return spec.model_id if spec else config.GATE_BEDROCK_ALIAS


def breaker_open() -> bool:
    return time.time() < _BREAKER["open_until"]


def _breaker_note(ok: bool) -> None:
    if ok:
        _BREAKER["fails"] = 0
        return
    _BREAKER["fails"] += 1
    if _BREAKER["fails"] >= config.GATE_BEDROCK_BREAKER_FAILS:
        _BREAKER["open_until"] = time.time() + config.GATE_BEDROCK_BREAKER_COOLDOWN_S
        _BREAKER["fails"] = 0
        logger.warning("gate_bedrock: breaker ABERTO por %ds após falhas consecutivas",
                       config.GATE_BEDROCK_BREAKER_COOLDOWN_S)


def analyze_new_litter_with_bedrock(
    first_frame: Path,
    last_frame: Path,
    camera_context: Optional[dict[str, str]] = None,
    request_id: Optional[str] = None,
    prior_window_context: Optional[str] = None,
    mid_frames: Optional[list[Path]] = None,
) -> dg.GeminiNewLitterInferenceResult:
    """Gate V1 em um modelo do Bedrock. Levanta `BedrockGateError` em qualquer falha."""
    alias = config.GATE_BEDROCK_ALIAS
    if breaker_open():
        raise BedrockGateError("bedrock gate breaker open")

    image_paths = [first_frame, *(mid_frames or []), last_frame]
    try:
        payload = detector_bedrock.prepare_images(
            image_paths, mode="low",
            width=config.GATE_BEDROCK_IMG_WIDTH, quality=config.GATE_BEDROCK_IMG_QUALITY)
    except Exception as exc:  # noqa: BLE001 — frame ilegível não é falha do Bedrock
        raise BedrockGateError(f"prepare_images: {type(exc).__name__}: {exc}") from exc
    if payload.n_dropped:
        # 5 frames de 640 px ficam muito abaixo do teto; se cortou, a medida não vale.
        raise BedrockGateError(f"payload: {payload.n_dropped} frame(s) cortado(s) para caber no teto")

    system_prompt = dg.new_litter_system_prompt(config.GATE_BEDROCK_PROMPT_VARIANT)
    user_prompt = dg._new_litter_user_prompt(
        first_frame.name, last_frame.name, camera_context,
        prior_window_context=prior_window_context, mosaic=False,
        mid_frame_names=[f.name for f in mid_frames] if mid_frames else None,
    )
    res = detector_bedrock.converse(
        alias, system_prompt, user_prompt, payload.blobs, GeminiNewLitterReport,
        max_tokens=config.GATE_BEDROCK_MAX_OUTPUT_TOKENS, force_mode="text",
        timeout_tries=config.GATE_BEDROCK_TIMEOUT_TRIES,
        deadline_s=config.GATE_BEDROCK_DEADLINE_S,
        attempt_timeout_s=config.GATE_BEDROCK_ATTEMPT_TIMEOUT_S,
    )
    if res.error or not res.json_valid or res.report is None:
        _breaker_note(ok=False)
        raise BedrockGateError(f"{alias}: {res.error or 'json invalido'}")
    _breaker_note(ok=True)

    report = res.report
    report.waste_type = dg.normalize_waste_type(report.waste_type)
    report.confidence_0_100 = max(0, min(100, int(report.confidence_0_100)))
    raw_new_litter, raw_conf = bool(report.new_litter_detected), int(report.confidence_0_100)
    report = apply_v1_gate(report)

    usage = GeminiUsage(
        input_tokens=res.tok_in, output_tokens=res.tok_out, thinking_tokens=0,
        total_tokens=res.tok_in + res.tok_out, estimated_cost_usd=res.cost_usd,
    )
    logger.info(json.dumps({
        "event": "bedrock_new_litter_gate_ok", "request_id": request_id, "model": model_id(),
        "latency_ms": res.latency_ms, "input_tokens": res.tok_in, "output_tokens": res.tok_out,
        "first_frame": first_frame.name, "last_frame": last_frame.name,
        "raw_new_litter": raw_new_litter, "raw_confidence": raw_conf,
        "new_litter": bool(report.new_litter_detected), "confidence": int(report.confidence_0_100),
    }, ensure_ascii=False))
    return dg.GeminiNewLitterInferenceResult(
        report=report, usage=usage, latency_ms=res.latency_ms, model=model_id(),
        raw_json=res.raw_text, is_maintenance=False, prompt_version="current",
    )
