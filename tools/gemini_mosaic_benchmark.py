#!/usr/bin/env python3
"""Benchmark Gemini with 6-frame mosaics across multiple layouts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFile, ImageOps
from pydantic import BaseModel, Field

ImageFile.LOAD_TRUNCATED_IMAGES = True


SYSTEM_PROMPT = (
    "Voce e um auditor visual de descarte irregular em via publica no Brasil. "
    "Responda APENAS JSON valido no schema solicitado."
)

LAYOUTS: dict[str, dict[str, Any]] = {
    "3x2": {
        "group_sizes": [6],
        "grid": (3, 2),
    },
    "3x1x2": {
        "group_sizes": [3, 3],
        "grid": (3, 1),
    },
    "2x1x3": {
        "group_sizes": [2, 2, 2],
        "grid": (2, 1),
    },
}


class BBoxNorm(BaseModel):
    x: float
    y: float
    w: float
    h: float


class FrameSelectionOutput(BaseModel):
    infraction_confirmed: bool
    event_type: str = "none"  # disposal_with_offender | new_litter_without_offender | none
    new_litter_detected: bool = False
    offender_detected: bool = False
    is_new_object_vs_baseline: bool | None = None
    persistent_after_appearance: bool | None = None
    confidence_0_100: int = Field(default=0, ge=0, le=100)
    evidence_summary: str = ""
    primary_frame_id: str | None = None
    offender_best_frame_id: str | None = None
    offender_visibility_score_0_100: int | None = Field(default=0, ge=0, le=100)
    detected_frame_ids: list[str] = Field(default_factory=list)
    infraction_bbox_norm: BBoxNorm | None = None


@dataclass
class CaseInfo:
    case_id: str
    bucket: str
    frame_map: dict[str, Path]


@dataclass
class PrefilterConfig:
    enabled: bool
    motion_diff_threshold: int = 18
    motion_ratio_threshold: float = 0.02
    dedup_hamming_threshold: int = 2
    min_frames_to_send: int = 2
    keep_last_frame: bool = True


MODEL_PRICING_PER_1M: list[tuple[re.Pattern[str], float, float, str]] = [
    (
        re.compile(r"^gemini-2\.5-flash-lite", re.IGNORECASE),
        0.10,
        0.40,
        "Gemini Developer API pricing (2.5 Flash-Lite standard text/image/video)",
    ),
    (
        re.compile(r"^gemini-2\.5-flash(?!-lite)", re.IGNORECASE),
        0.30,
        2.50,
        "Gemini Developer API pricing (2.5 Flash standard text/image/video)",
    ),
    (
        re.compile(r"^gemini-2\.0-flash-lite", re.IGNORECASE),
        0.10,
        0.40,
        "Gemini Developer API pricing (2.0 Flash-Lite standard text/image/video)",
    ),
    (
        re.compile(r"^gemini-2\.0-flash(?!-lite)", re.IGNORECASE),
        0.10,
        0.40,
        "Gemini Developer API pricing (2.0 Flash standard text/image/video)",
    ),
]


def _resolve_model_pricing(model: str) -> tuple[float, float, str]:
    env_input = os.getenv("GEMINI_PRICE_INPUT_PER_1M", "").strip()
    env_output = os.getenv("GEMINI_PRICE_OUTPUT_PER_1M", "").strip()
    if env_input and env_output:
        try:
            return (
                float(env_input),
                float(env_output),
                "env_override:GEMINI_PRICE_INPUT_PER_1M/GEMINI_PRICE_OUTPUT_PER_1M",
            )
        except Exception:
            pass

    for pattern, in_price, out_price, source in MODEL_PRICING_PER_1M:
        if pattern.search(model):
            return in_price, out_price, source

    # Backward-compatible fallback used before model-aware pricing.
    return 0.10, 0.40, "fallback_default_legacy"


def _load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'").strip('"')
    return data


def _load_api_key(env_path: Path) -> str:
    env_data = _load_env_file(env_path)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if env_data.get(key):
            return env_data[key]
    return os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")


def _list_cases(dataset_root: Path) -> list[CaseInfo]:
    buckets = [("Infrator", "infrator"), ("Sem nada", "sem_nada")]
    cases: list[CaseInfo] = []
    for folder_name, key_prefix in buckets:
        bucket_dir = dataset_root / folder_name
        if not bucket_dir.exists():
            continue
        for case_dir in sorted([p for p in bucket_dir.iterdir() if p.is_dir()]):
            frames = sorted(case_dir.glob("*.jpg"))
            if len(frames) < 6:
                continue
            selected = frames[:6]
            frame_map = {f"F{i}": p for i, p in enumerate(selected)}
            case_id = f"{key_prefix}_{case_dir.name}"
            cases.append(CaseInfo(case_id=case_id, bucket=folder_name, frame_map=frame_map))
    return sorted(cases, key=lambda c: c.case_id)


def _build_mosaic(tile_paths: list[tuple[str, Path]], cols: int, rows: int, out_path: Path) -> Path:
    cell_w, cell_h = 640, 360
    canvas = Image.new("RGB", (cols * cell_w, rows * cell_h), color=(0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    for idx, (frame_id, frame_path) in enumerate(tile_paths):
        img = Image.open(frame_path).convert("RGB")
        cell = ImageOps.contain(img, (cell_w, cell_h))
        tile = Image.new("RGB", (cell_w, cell_h), color=(0, 0, 0))
        x0 = (cell_w - cell.width) // 2
        y0 = (cell_h - cell.height) // 2
        tile.paste(cell, (x0, y0))

        tile_draw = ImageDraw.Draw(tile)
        tile_draw.rectangle((0, 0, cell_w, 30), fill=(0, 0, 0))
        tile_draw.text((8, 8), f"{frame_id} | {frame_path.name}", fill=(255, 255, 0))

        r = idx // cols
        c = idx % cols
        y0 = r * cell_h
        x0 = c * cell_w
        canvas.paste(tile, (x0, y0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="JPEG", quality=90)
    return out_path


def _gray_array(path: Path, size: tuple[int, int] = (256, 144)) -> np.ndarray:
    return np.array(Image.open(path).convert("L").resize(size), dtype=np.uint8)


def _ahash(path: Path, size: int = 8) -> np.ndarray:
    arr = np.array(Image.open(path).convert("L").resize((size, size)), dtype=np.float32)
    avg = float(arr.mean())
    return (arr >= avg).astype(np.uint8).flatten()


def _hamming_distance(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def _chunk_ids(frame_ids: list[str], group_sizes: list[int]) -> list[list[str]]:
    groups: list[list[str]] = []
    cursor = 0
    for sz in group_sizes:
        group = frame_ids[cursor : cursor + sz]
        groups.append(group)
        cursor += sz
    return groups


def _prefilter_frames(case: CaseInfo, cfg: PrefilterConfig) -> dict[str, Any]:
    ordered_ids = sorted(case.frame_map.keys(), key=lambda x: int(x[1:]))
    if not cfg.enabled or len(ordered_ids) <= cfg.min_frames_to_send:
        return {
            "enabled": cfg.enabled,
            "original_frame_ids": ordered_ids,
            "kept_frame_ids": ordered_ids,
            "dropped_frame_ids": [],
            "skipped_case": False,
            "reason": None,
            "motion_max_ratio": None,
            "motion_mean_ratio": None,
        }

    grays = [_gray_array(case.frame_map[fid]) for fid in ordered_ids]
    hashes = [_ahash(case.frame_map[fid]) for fid in ordered_ids]

    motion_ratios: list[float] = []
    keep_indices: list[int] = [0]
    max_motion_idx = 0
    max_motion_ratio = -1.0
    for i in range(1, len(ordered_ids)):
        diff = np.abs(grays[i].astype(np.int16) - grays[i - 1].astype(np.int16))
        ratio = float((diff > cfg.motion_diff_threshold).sum() / diff.size)
        motion_ratios.append(ratio)
        if ratio > max_motion_ratio:
            max_motion_ratio = ratio
            max_motion_idx = i
        if ratio >= cfg.motion_ratio_threshold:
            keep_indices.append(i)

    force_keep = {0, max_motion_idx}
    if cfg.keep_last_frame:
        force_keep.add(len(ordered_ids) - 1)
    keep_indices.extend(sorted(force_keep))
    keep_indices = sorted(set(keep_indices))

    # Dedup stage (perceptual hash) on the motion-selected set.
    dedup_indices: list[int] = []
    for idx in keep_indices:
        if idx in force_keep:
            if idx not in dedup_indices:
                dedup_indices.append(idx)
            continue
        if not dedup_indices:
            dedup_indices.append(idx)
            continue
        min_dist = min(_hamming_distance(hashes[idx], hashes[j]) for j in dedup_indices)
        if min_dist > cfg.dedup_hamming_threshold:
            dedup_indices.append(idx)

    for idx in sorted(force_keep):
        if idx not in dedup_indices:
            dedup_indices.append(idx)
    dedup_indices = sorted(set(dedup_indices))

    if len(dedup_indices) < cfg.min_frames_to_send:
        # Fail-safe: keep first and last so the model still has minimal temporal context.
        dedup_indices = sorted(set([0, len(ordered_ids) - 1]))

    kept_ids = [ordered_ids[i] for i in dedup_indices]
    dropped_ids = [fid for fid in ordered_ids if fid not in kept_ids]
    skipped_case = len(kept_ids) < cfg.min_frames_to_send
    reason = "insufficient_frames_after_prefilter" if skipped_case else None

    return {
        "enabled": True,
        "original_frame_ids": ordered_ids,
        "kept_frame_ids": kept_ids,
        "dropped_frame_ids": dropped_ids,
        "kept_count": len(kept_ids),
        "dropped_count": len(dropped_ids),
        "skipped_case": skipped_case,
        "reason": reason,
        "motion_max_ratio": round(max(motion_ratios), 6) if motion_ratios else 0.0,
        "motion_mean_ratio": round(float(np.mean(motion_ratios)), 6) if motion_ratios else 0.0,
    }


def _usage_to_dict(resp: Any, model: str) -> dict[str, Any]:
    in_price, out_price, pricing_source = _resolve_model_pricing(model)
    md = getattr(resp, "usage_metadata", None)
    if not md:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "pricing_input_per_1m_usd": in_price,
            "pricing_output_per_1m_usd": out_price,
            "pricing_source": pricing_source,
        }
    input_tokens = int(getattr(md, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(md, "candidates_token_count", 0) or 0)
    total_tokens = int(getattr(md, "total_token_count", 0) or (input_tokens + output_tokens))
    estimated_cost = (input_tokens / 1_000_000.0) * in_price + (output_tokens / 1_000_000.0) * out_price
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(estimated_cost, 8),
        "pricing_input_per_1m_usd": in_price,
        "pricing_output_per_1m_usd": out_price,
        "pricing_source": pricing_source,
    }


def _extract_text(resp: Any) -> str:
    text = getattr(resp, "text", None)
    if text:
        return text
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = candidates[0].content.parts if candidates[0].content else []
    chunks = [getattr(part, "text", "") for part in parts if getattr(part, "text", None)]
    if not chunks:
        raise RuntimeError("Gemini returned empty text")
    return "\n".join(chunks)


def _parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    # Fallback for outputs that include text around JSON.
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

    # Last-resort parser for truncated/invalid JSON: recover key fields via regex.
    recovered: dict[str, Any] = {}
    bool_re = re.compile(
        r'"(?P<k>infraction_confirmed|infraction_detected|infraction_found|has_infraction|infraction|new_litter_detected|offender_detected|is_new_object_vs_baseline|persistent_after_appearance)"\s*:\s*(?P<v>true|false|null)',
        re.IGNORECASE,
    )
    frame_re = re.compile(r'"(?P<k>primary_frame_id|offender_best_frame_id)"\s*:\s*"(?P<v>[^"]+)"', re.IGNORECASE)
    conf_re = re.compile(r'"(?P<k>confidence_0_100|confidence|offender_visibility_score_0_100)"\s*:\s*(?P<v>\d+)', re.IGNORECASE)

    for m in bool_re.finditer(text):
        key = m.group("k")
        val = m.group("v").lower()
        if val == "null":
            recovered[key] = None
        else:
            recovered[key] = val == "true"
    for m in frame_re.finditer(text):
        recovered[m.group("k")] = m.group("v")
    for m in conf_re.finditer(text):
        recovered[m.group("k")] = int(m.group("v"))

    frame_hits = sorted(set(re.findall(r"\bF[0-5]\b", text.upper())))
    if frame_hits:
        recovered["detected_frame_ids"] = frame_hits

    if recovered:
        return recovered
    raise ValueError("No JSON object found in model output")


def _clamp_int(value: Any, default: int = 0) -> int:
    try:
        v = int(value)
    except Exception:
        v = default
    return max(0, min(100, v))


def _sanitize_result(raw: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    infraction_value = raw.get("infraction_confirmed")
    if infraction_value is None:
        infraction_value = raw.get("infraction_detected")
    if infraction_value is None:
        infraction_value = raw.get("infraction_found")
    if infraction_value is None:
        infraction_value = raw.get("has_infraction")

    event_type = str(raw.get("event_type") or "").strip().lower()
    valid_event_types = {"disposal_with_offender", "new_litter_without_offender", "none"}
    if event_type not in valid_event_types:
        event_type = "none"

    new_litter_detected = bool(raw.get("new_litter_detected", False))
    offender_detected = bool(raw.get("offender_detected", False))
    is_new_object_vs_baseline = raw.get("is_new_object_vs_baseline")
    if is_new_object_vs_baseline is not None:
        is_new_object_vs_baseline = bool(is_new_object_vs_baseline)
    persistent_after_appearance = raw.get("persistent_after_appearance")
    if persistent_after_appearance is not None:
        persistent_after_appearance = bool(persistent_after_appearance)

    detected_raw = (
        raw.get("detected_frame_ids")
        or raw.get("frames_with_infraction")
        or raw.get("infraction_frames_id")
        or []
    )
    detected = []
    for value in detected_raw:
        if not isinstance(value, str):
            continue
        candidate = value.strip().upper()
        if candidate in allowed:
            detected.append(candidate)

    primary = raw.get("primary_frame_id")
    if isinstance(primary, str):
        primary = primary.strip().upper()
    if primary not in allowed:
        primary = None
    offender = raw.get("offender_best_frame_id")
    if isinstance(offender, str):
        offender = offender.strip().upper()
    if offender not in allowed:
        offender = None

    if primary is None and detected:
        primary = detected[0]
    if offender is None and primary is not None:
        offender = primary

    confidence_raw = raw.get("confidence_0_100")
    if confidence_raw is None:
        confidence_raw = raw.get("confidence")

    offender_visibility_raw = raw.get("offender_visibility_score_0_100")
    if offender_visibility_raw is None:
        offender_visibility_raw = confidence_raw

    bbox = raw.get("infraction_bbox_norm")
    if isinstance(bbox, dict):
        try:
            bbox = {k: round(float(bbox[k]), 4) for k in ("x", "y", "w", "h")}
        except Exception:
            bbox = None
    else:
        bbox = None
    return {
        "infraction_confirmed": bool(infraction_value),
        "event_type": event_type,
        "new_litter_detected": new_litter_detected,
        "offender_detected": offender_detected,
        "is_new_object_vs_baseline": is_new_object_vs_baseline,
        "persistent_after_appearance": persistent_after_appearance,
        "confidence_0_100": _clamp_int(confidence_raw, 0),
        "evidence_summary": str(raw.get("evidence_summary") or "").strip()[:500],
        "primary_frame_id": primary,
        "offender_best_frame_id": offender,
        "offender_visibility_score_0_100": _clamp_int(offender_visibility_raw, 0),
        "detected_frame_ids": detected,
        "infraction_bbox_norm": bbox,
    }


def _call_gemini(
    client: genai.Client,
    model: str,
    timeout_s: int,
    retries: int,
    case_id: str,
    layout: str,
    mosaic_path: Path,
    available_frame_ids: list[str],
) -> dict[str, Any]:
    prompt = (
        "Analise o mosaico e classifique APENAS eventos de descarte irregular de RESIDUO SOLIDO.\n"
        "Ignore fumaça, emissao de poluentes, transito, estacionamento, pedestre parado e qualquer evento sem lixo solido visivel.\n"
        f"Frames validos neste mosaico: {', '.join(available_frame_ids)}.\n"
        "Retorne JSON com EXATAMENTE estas chaves:\n"
        "infraction_confirmed, event_type, new_litter_detected, offender_detected, "
        "is_new_object_vs_baseline, persistent_after_appearance, confidence_0_100, evidence_summary, primary_frame_id, "
        "offender_best_frame_id, offender_visibility_score_0_100, detected_frame_ids, infraction_bbox_norm.\n"
        "event_type deve ser: disposal_with_offender, new_litter_without_offender, none.\n"
        "Regras de decisao:\n"
        "- disposal_with_offender: existe ato de descarte por pessoa/veiculo. Preferencialmente com persistencia visivel depois.\n"
        "- Se houver ato claro de descarte em >=2 frames, mas a persistencia nao for verificavel por oclusao/qualidade, use disposal_with_offender com confidence moderada e persistent_after_appearance=null.\n"
        "- new_litter_without_offender: nao ha infrator claro, mas surge lixo NOVO e ele permanece nos frames posteriores.\n"
        "- none: qualquer outro caso.\n"
        "Para new_litter_without_offender, so confirme quando houver persistencia apos surgimento.\n"
        "Se houver apenas 1 frame ou evidencia insuficiente, retorne none e infraction_confirmed=false.\n"
        "Se houver duvida, retorne none.\n"
        "Retorne IDs de frame apenas nesse conjunto.\n"
        "Escolha primary_frame_id como o melhor frame para evidenciar a infracao.\n"
        "Escolha offender_best_frame_id como o melhor frame para identificar o infrator/veiculo (se visivel).\n"
        "Se infraction_confirmed=true, primary_frame_id NAO pode ser null.\n"
        "Se nao houver infracao, deixe primary_frame_id e offender_best_frame_id como null.\n"
        "infraction_bbox_norm deve ser em coordenadas normalizadas [0,1] do mosaico completo."
    )

    config = types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=2048,
        response_mime_type="application/json",
        response_schema=FrameSelectionOutput.model_json_schema(),
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    attempts = max(0, retries) + 1
    last_error: Exception | None = None
    in_price, out_price, pricing_source = _resolve_model_pricing(model)
    last_usage: dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "pricing_input_per_1m_usd": in_price,
        "pricing_output_per_1m_usd": out_price,
        "pricing_source": pricing_source,
    }
    last_raw_text = ""
    started = time.monotonic()
    for attempt in range(1, attempts + 1):
        try:
            data = mosaic_path.read_bytes()
            req_started = time.monotonic()
            resp = client.models.generate_content(
                model=model,
                contents=[
                    SYSTEM_PROMPT,
                    prompt,
                    types.Part.from_bytes(data=data, mime_type="image/jpeg"),
                ],
                config=config,
            )
            req_ms = int((time.monotonic() - req_started) * 1000)
            text = _extract_text(resp)
            usage = _usage_to_dict(resp, model)
            last_usage = usage
            last_raw_text = text
            payload = _parse_json_text(text)
            payload = FrameSelectionOutput.model_validate(payload).model_dump()
            sanitized = _sanitize_result(payload, set(available_frame_ids))
            return {
                "success": True,
                "case_id": case_id,
                "layout": layout,
                "mosaic_file": str(mosaic_path),
                "available_frame_ids": available_frame_ids,
                "latency_ms": req_ms,
                "usage": usage,
                "result": sanitized,
                "raw_json": text,
                "attempt": attempt,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 3))
    return {
        "success": False,
        "case_id": case_id,
        "layout": layout,
        "mosaic_file": str(mosaic_path),
        "available_frame_ids": available_frame_ids,
        "error": str(last_error),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "usage": last_usage,
        "raw_text": last_raw_text,
    }


def _aggregate_layout(layout_calls: list[dict[str, Any]], frame_map: dict[str, Path]) -> dict[str, Any]:
    best_id: str | None = None
    best_score = -1
    all_detected: list[str] = []
    infraction_confirmed = False
    event_type = "none"
    offender_detected = False
    new_litter_detected = False
    persistent_after_appearance = None
    is_new_object_vs_baseline = None
    best_bbox: dict[str, float] | None = None
    evidence = ""
    confidence = 0

    for call in layout_calls:
        if not call.get("success"):
            continue
        result = call["result"]
        call_event = result.get("event_type") or "none"
        call_persistent = result.get("persistent_after_appearance")
        call_new_obj = result.get("is_new_object_vs_baseline")
        call_offender = bool(result.get("offender_detected"))
        call_new_litter = bool(result.get("new_litter_detected"))

        call_positive = False
        if call_event == "disposal_with_offender":
            call_positive = call_offender and (call_persistent is True)
        elif call_event == "new_litter_without_offender":
            call_positive = call_new_litter and (call_new_obj is True) and (call_persistent is True)
        elif bool(result.get("infraction_confirmed")) and (call_persistent is True):
            # Backward compatibility fallback.
            call_positive = True

        if call_positive:
            infraction_confirmed = True
            if event_type == "none":
                event_type = call_event if call_event in {"disposal_with_offender", "new_litter_without_offender"} else "none"
            offender_detected = offender_detected or call_offender
            new_litter_detected = new_litter_detected or call_new_litter
            persistent_after_appearance = True
            if call_new_obj is True:
                is_new_object_vs_baseline = True

        detected = result.get("detected_frame_ids") or []
        for frame_id in detected:
            if frame_id not in all_detected:
                all_detected.append(frame_id)

        if not call_positive:
            continue

        candidate = result.get("offender_best_frame_id") or result.get("primary_frame_id")
        score = int(result.get("offender_visibility_score_0_100") or 0) * 1000 + int(
            result.get("confidence_0_100") or 0
        )
        if candidate and score > best_score:
            best_score = score
            best_id = candidate
            best_bbox = result.get("infraction_bbox_norm")
            evidence = result.get("evidence_summary") or evidence
            confidence = int(result.get("confidence_0_100") or confidence)

    if infraction_confirmed and best_id is None and all_detected:
        best_id = all_detected[0]

    selected_file = str(frame_map[best_id]) if best_id and best_id in frame_map else None
    return {
        "infraction_confirmed": infraction_confirmed,
        "event_type": event_type,
        "new_litter_detected": new_litter_detected,
        "offender_detected": offender_detected,
        "is_new_object_vs_baseline": is_new_object_vs_baseline,
        "persistent_after_appearance": persistent_after_appearance,
        "selected_frame_id": best_id,
        "selected_frame_file": selected_file,
        "detected_frame_ids_union": all_detected,
        "confidence_0_100": confidence,
        "evidence_summary": evidence,
        "infraction_bbox_norm": best_bbox,
    }


def _aggregate_layout_with_policy(
    layout_calls: list[dict[str, Any]],
    frame_map: dict[str, Path],
    allow_disposal_without_persistence: bool,
    disposal_confidence_floor: int,
    disposal_min_detected_frames: int,
    veto_tail_single_frame_disposal: bool,
) -> dict[str, Any]:
    best_id: str | None = None
    best_score = -1
    all_detected: list[str] = []
    infraction_confirmed = False
    event_type = "none"
    offender_detected = False
    new_litter_detected = False
    persistent_after_appearance = None
    is_new_object_vs_baseline = None
    best_bbox: dict[str, float] | None = None
    evidence = ""
    confidence = 0

    last_frame_id = None
    if frame_map:
        def _frame_rank(fid: str) -> tuple[int, str]:
            try:
                return (int(fid[1:]), fid)
            except Exception:
                return (-1, fid)

        last_frame_id = max(frame_map.keys(), key=_frame_rank)

    for call in layout_calls:
        if not call.get("success"):
            continue
        result = call["result"]
        call_event = result.get("event_type") or "none"
        call_persistent = result.get("persistent_after_appearance")
        call_new_obj = result.get("is_new_object_vs_baseline")
        call_offender = bool(result.get("offender_detected"))
        call_new_litter = bool(result.get("new_litter_detected"))
        call_conf = int(result.get("confidence_0_100") or 0)
        detected = result.get("detected_frame_ids") or []
        detected_count = len(detected)

        call_positive = False
        if call_event == "disposal_with_offender":
            if call_offender and (call_persistent is True):
                call_positive = True
            elif (
                allow_disposal_without_persistence
                and call_offender
                and call_conf >= disposal_confidence_floor
                and detected_count >= disposal_min_detected_frames
            ):
                call_positive = True
            if (
                call_positive
                and veto_tail_single_frame_disposal
                and detected_count == 1
                and last_frame_id is not None
                and detected[0] == last_frame_id
            ):
                call_positive = False
        elif call_event == "new_litter_without_offender":
            call_positive = call_new_litter and (call_new_obj is True) and (call_persistent is True)
        elif bool(result.get("infraction_confirmed")) and (call_persistent is True):
            call_positive = True

        if call_positive:
            infraction_confirmed = True
            if event_type == "none":
                event_type = call_event if call_event in {"disposal_with_offender", "new_litter_without_offender"} else "none"
            offender_detected = offender_detected or call_offender
            new_litter_detected = new_litter_detected or call_new_litter
            if call_persistent is True:
                persistent_after_appearance = True
            if call_new_obj is True:
                is_new_object_vs_baseline = True

        for frame_id in detected:
            if frame_id not in all_detected:
                all_detected.append(frame_id)

        if not call_positive:
            continue

        candidate = result.get("offender_best_frame_id") or result.get("primary_frame_id")
        score = int(result.get("offender_visibility_score_0_100") or 0) * 1000 + call_conf
        if candidate and score > best_score:
            best_score = score
            best_id = candidate
            best_bbox = result.get("infraction_bbox_norm")
            evidence = result.get("evidence_summary") or evidence
            confidence = call_conf

    if infraction_confirmed and best_id is None and all_detected:
        best_id = all_detected[0]

    selected_file = str(frame_map[best_id]) if best_id and best_id in frame_map else None
    return {
        "infraction_confirmed": infraction_confirmed,
        "event_type": event_type,
        "new_litter_detected": new_litter_detected,
        "offender_detected": offender_detected,
        "is_new_object_vs_baseline": is_new_object_vs_baseline,
        "persistent_after_appearance": persistent_after_appearance,
        "selected_frame_id": best_id,
        "selected_frame_file": selected_file,
        "detected_frame_ids_union": all_detected,
        "confidence_0_100": confidence,
        "evidence_summary": evidence,
        "infraction_bbox_norm": best_bbox,
    }


def _run_case(
    client: genai.Client,
    model: str,
    timeout_s: int,
    retries: int,
    output_root: Path,
    case: CaseInfo,
    layouts: dict[str, dict[str, Any]],
    prefilter: PrefilterConfig,
    allow_disposal_without_persistence: bool,
    disposal_confidence_floor: int,
    disposal_min_detected_frames: int,
    veto_tail_single_frame_disposal: bool,
) -> dict[str, Any]:
    case_out = output_root / "mosaics" / case.case_id
    prefilter_result = _prefilter_frames(case, prefilter)
    filtered_frame_map = {fid: case.frame_map[fid] for fid in prefilter_result["kept_frame_ids"]}
    case_result: dict[str, Any] = {
        "case_id": case.case_id,
        "bucket": case.bucket,
        "frame_map": {k: str(v) for k, v in case.frame_map.items()},
        "prefilter": prefilter_result,
        "layouts": {},
    }

    for layout_name, cfg in layouts.items():
        layout_started = time.monotonic()
        cols, rows = cfg["grid"]
        groups: list[list[str]] = _chunk_ids(list(filtered_frame_map.keys()), cfg["group_sizes"])
        call_inputs: list[tuple[Path, list[str]]] = []
        for idx, group in enumerate(groups, start=1):
            if not group:
                continue
            tile_paths = [(fid, filtered_frame_map[fid]) for fid in group]
            out_img = case_out / layout_name / f"mosaic_{idx}.jpg"
            _build_mosaic(tile_paths, cols=cols, rows=rows, out_path=out_img)
            call_inputs.append((out_img, group))

        calls: list[dict[str, Any]] = []
        if call_inputs and not prefilter_result["skipped_case"]:
            with ThreadPoolExecutor(max_workers=len(call_inputs)) as pool:
                future_map = {
                    pool.submit(
                        _call_gemini,
                        client,
                        model,
                        timeout_s,
                        retries,
                        case.case_id,
                        layout_name,
                        mosaic_path,
                        frame_ids,
                    ): (mosaic_path, frame_ids)
                    for mosaic_path, frame_ids in call_inputs
                }
                for fut in as_completed(future_map):
                    calls.append(fut.result())

        agg = _aggregate_layout_with_policy(
            calls,
            case.frame_map,
            allow_disposal_without_persistence=allow_disposal_without_persistence,
            disposal_confidence_floor=disposal_confidence_floor,
            disposal_min_detected_frames=disposal_min_detected_frames,
            veto_tail_single_frame_disposal=veto_tail_single_frame_disposal,
        )
        wall_ms = int((time.monotonic() - layout_started) * 1000)
        ok_calls = [c for c in calls if c.get("success")]
        usage = {
            "input_tokens": sum(int(c["usage"]["input_tokens"]) for c in calls),
            "output_tokens": sum(int(c["usage"]["output_tokens"]) for c in calls),
            "total_tokens": sum(int(c["usage"]["total_tokens"]) for c in calls),
            "estimated_cost_usd": round(sum(float(c["usage"]["estimated_cost_usd"]) for c in calls), 8),
        }

        if prefilter_result["skipped_case"]:
            agg = {
                "infraction_confirmed": False,
                "event_type": "none",
                "new_litter_detected": False,
                "offender_detected": False,
                "is_new_object_vs_baseline": None,
                "persistent_after_appearance": None,
                "selected_frame_id": None,
                "selected_frame_file": None,
                "detected_frame_ids_union": [],
                "confidence_0_100": 0,
                "evidence_summary": "Skipped by local prefilter",
                "infraction_bbox_norm": None,
            }
            usage = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            }
            calls = []
            ok_calls = []

        selected_copy = None
        if agg["selected_frame_file"]:
            selected_src = Path(agg["selected_frame_file"])
            selected_dir = output_root / "selected_frames" / case.case_id
            selected_dir.mkdir(parents=True, exist_ok=True)
            selected_copy_path = selected_dir / f"{layout_name}_{agg['selected_frame_id']}_{selected_src.name}"
            shutil.copy2(selected_src, selected_copy_path)
            selected_copy = str(selected_copy_path)

        case_result["layouts"][layout_name] = {
            "request_count": len(calls),
            "request_success_count": len(ok_calls),
            "request_error_count": len(calls) - len(ok_calls),
            "prefilter_skipped_case": bool(prefilter_result["skipped_case"]),
            "frames_sent_to_model_count": sum(len(c.get("available_frame_ids") or []) for c in calls),
            "layout_wall_time_ms": wall_ms,
            "avg_request_latency_ms": round(
                sum(int(c.get("latency_ms", 0)) for c in ok_calls) / len(ok_calls), 2
            )
            if ok_calls
            else None,
            "max_request_latency_ms": max((int(c.get("latency_ms", 0)) for c in ok_calls), default=None),
            "usage": usage,
            "aggregate": agg,
            "selected_frame_copy": selected_copy,
            "calls": calls,
        }

    return case_result


def _summarize(report: dict[str, Any], layouts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_layout: dict[str, dict[str, Any]] = {}
    prefilter_entries = [c.get("prefilter", {}) for c in report["cases"]]
    for layout_name in layouts:
        entries = [c.get("layouts", {}).get(layout_name) for c in report["cases"]]
        entries = [e for e in entries if e]
        total_calls = sum(e["request_count"] for e in entries)
        ok_calls = sum(e["request_success_count"] for e in entries)
        selected = sum(1 for e in entries if e["aggregate"]["selected_frame_id"])
        frames_sent_total = sum(int(e.get("frames_sent_to_model_count", 0)) for e in entries)
        per_layout[layout_name] = {
            "cases_total": len(entries),
            "calls_total": total_calls,
            "calls_success": ok_calls,
            "calls_error": total_calls - ok_calls,
            "prefilter_skipped_cases": sum(1 for e in entries if e.get("prefilter_skipped_case")),
            "frames_sent_total": frames_sent_total,
            "frames_sent_avg_per_case": round(frames_sent_total / max(len(entries), 1), 2),
            "selected_frame_rate": round(selected / max(len(entries), 1), 4),
            "avg_layout_wall_time_ms": round(
                sum(int(e["layout_wall_time_ms"]) for e in entries) / max(len(entries), 1), 2
            ),
            "avg_request_latency_ms": round(
                sum(float(e["avg_request_latency_ms"] or 0) for e in entries) / max(len(entries), 1), 2
            ),
            "p95_layout_wall_time_ms": round(
                np.percentile([int(e["layout_wall_time_ms"]) for e in entries], 95), 2
            )
            if entries
            else None,
            "input_tokens": sum(int(e["usage"]["input_tokens"]) for e in entries),
            "output_tokens": sum(int(e["usage"]["output_tokens"]) for e in entries),
            "total_tokens": sum(int(e["usage"]["total_tokens"]) for e in entries),
            "estimated_cost_usd": round(sum(float(e["usage"]["estimated_cost_usd"]) for e in entries), 8),
        }
    report["prefilter_summary"] = {
        "enabled_cases": sum(1 for p in prefilter_entries if p.get("enabled")),
        "skipped_cases": sum(1 for p in prefilter_entries if p.get("skipped_case")),
        "original_frames_total": sum(len(p.get("original_frame_ids", [])) for p in prefilter_entries),
        "kept_frames_total": sum(len(p.get("kept_frame_ids", [])) for p in prefilter_entries),
        "dropped_frames_total": sum(len(p.get("dropped_frame_ids", [])) for p in prefilter_entries),
    }
    return per_layout


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Gemini mosaic benchmark for SAIRA test cases.")
    parser.add_argument(
        "--dataset-root",
        default=r"c:\saira\services\yolo-worker-vm\Teste gemini",
        help="Root with 'Infrator' and 'Sem nada' folders.",
    )
    parser.add_argument(
        "--env-file",
        default=r"c:\saira\services\.env",
        help="Env file to read GEMINI_API_KEY/GOOGLE_API_KEY.",
    )
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    parser.add_argument("--timeout-s", type=int, default=25)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--cases-workers", type=int, default=4)
    parser.add_argument("--report-prefix", default="gemini_mosaic_benchmark")
    parser.add_argument(
        "--layouts",
        default="3x2,3x1x2,2x1x3",
        help="Comma-separated layouts to run. Available: 3x2,3x1x2,2x1x3",
    )
    parser.add_argument("--enable-prefilter", action="store_true", help="Enable local motion+dedup prefilter.")
    parser.add_argument("--motion-diff-threshold", type=int, default=18, help="Pixel diff threshold for motion mask.")
    parser.add_argument(
        "--motion-ratio-threshold",
        type=float,
        default=0.02,
        help="Min ratio of changed pixels to keep a frame after motion check.",
    )
    parser.add_argument(
        "--dedup-hamming-threshold",
        type=int,
        default=2,
        help="Max aHash hamming distance to consider frames duplicates.",
    )
    parser.add_argument("--prefilter-min-frames", type=int, default=2, help="Min frames required after prefilter.")
    parser.add_argument(
        "--allow-disposal-without-persistence",
        action="store_true",
        help="Allow disposal_with_offender to be positive without persistence when confidence/detected-frames are high.",
    )
    parser.add_argument(
        "--disposal-confidence-floor",
        type=int,
        default=80,
        help="Confidence floor for disposal_with_offender when persistence is absent.",
    )
    parser.add_argument(
        "--disposal-min-detected-frames",
        type=int,
        default=2,
        help="Minimum detected frames required to allow disposal_without_persistence.",
    )
    parser.add_argument(
        "--veto-tail-single-frame-disposal",
        action="store_true",
        help="Veto disposal_with_offender with single detected frame when that frame is the last frame (F5).",
    )
    args = parser.parse_args()

    api_key = _load_api_key(Path(args.env_file))
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY/GOOGLE_API_KEY not found in env file or environment.")

    dataset_root = Path(args.dataset_root)
    cases = _list_cases(dataset_root)
    if len(cases) != 8:
        print(f"WARNING: expected 8 cases, found {len(cases)}")

    selected_layouts = [x.strip() for x in str(args.layouts).split(",") if x.strip()]
    invalid = [x for x in selected_layouts if x not in LAYOUTS]
    if invalid:
        raise RuntimeError(f"Invalid layout(s): {invalid}. Available: {list(LAYOUTS.keys())}")
    active_layouts = {k: LAYOUTS[k] for k in selected_layouts}
    prefilter = PrefilterConfig(
        enabled=bool(args.enable_prefilter),
        motion_diff_threshold=int(args.motion_diff_threshold),
        motion_ratio_threshold=float(args.motion_ratio_threshold),
        dedup_hamming_threshold=int(args.dedup_hamming_threshold),
        min_frames_to_send=int(args.prefilter_min_frames),
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("c:/saira/tmp") / f"{args.report_prefix}_{ts}"
    output_root.mkdir(parents=True, exist_ok=True)
    report_in_price, report_out_price, report_pricing_source = _resolve_model_pricing(args.model)

    client = genai.Client(api_key=api_key)
    started = time.monotonic()
    case_results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.cases_workers)) as pool:
        futures = {
            pool.submit(
                _run_case,
                client,
                args.model,
                args.timeout_s,
                args.retries,
                output_root,
                case,
                active_layouts,
                prefilter,
                bool(args.allow_disposal_without_persistence),
                int(args.disposal_confidence_floor),
                int(args.disposal_min_detected_frames),
                bool(args.veto_tail_single_frame_disposal),
            ): case.case_id
            for case in cases
        }
        for fut in as_completed(futures):
            case_id = futures[fut]
            try:
                case_results.append(fut.result())
                print(f"[ok] case {case_id} done")
            except Exception as exc:  # noqa: BLE001
                print(f"[error] case {case_id} failed: {exc}")
                case_results.append(
                    {
                        "case_id": case_id,
                        "bucket": "unknown",
                        "frame_map": {},
                        "error": str(exc),
                        "layouts": {},
                    }
                )

    case_results = sorted(case_results, key=lambda c: c["case_id"])
    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": args.model,
        "pricing": {
            "input_per_1m_usd": report_in_price,
            "output_per_1m_usd": report_out_price,
            "source": report_pricing_source,
        },
        "dataset_root": str(dataset_root),
        "cases_total": len(cases),
        "layouts_tested": list(active_layouts.keys()),
        "cases": case_results,
        "summary_by_layout": {},
        "prefilter_config": {
            "enabled": prefilter.enabled,
            "motion_diff_threshold": prefilter.motion_diff_threshold,
            "motion_ratio_threshold": prefilter.motion_ratio_threshold,
            "dedup_hamming_threshold": prefilter.dedup_hamming_threshold,
            "min_frames_to_send": prefilter.min_frames_to_send,
        },
        "decision_policy": {
            "allow_disposal_without_persistence": bool(args.allow_disposal_without_persistence),
            "disposal_confidence_floor": int(args.disposal_confidence_floor),
            "disposal_min_detected_frames": int(args.disposal_min_detected_frames),
            "veto_tail_single_frame_disposal": bool(args.veto_tail_single_frame_disposal),
        },
        "total_wall_time_ms": int((time.monotonic() - started) * 1000),
        "output_root": str(output_root),
    }
    report["summary_by_layout"] = _summarize(report, active_layouts)

    report_path = Path("c:/saira/tmp") / f"{args.report_prefix}_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Report: {report_path}")
    for layout_name, summary in report["summary_by_layout"].items():
        print(
            f"{layout_name}: avg_wall={summary['avg_layout_wall_time_ms']}ms "
            f"avg_req={summary['avg_request_latency_ms']}ms "
            f"cost=${summary['estimated_cost_usd']} "
            f"selected_rate={summary['selected_frame_rate']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
