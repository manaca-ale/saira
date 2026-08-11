#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared logic for the Agent-3 false-positive screener benchmark (cam_11).

The screener runs AFTER Agent-2 already confirmed a disposal. It looks at the
before/after frames (+ a hi-res pile-zone crop) of an esp32_002 event and
decides whether a NEW disposal truly occurred, or the person merely
rummaged/disturbed the existing pile (catador) / just passed by.

Decision: is_real_new_disposal == False  ->  KILL (veta o FP).

Used by run_screener.py for both providers (Gemini 2.5 Flash via google-genai,
Claude Haiku 4.5 via AWS Bedrock).
"""
from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path

from PIL import Image

# Pile-zone bbox for esp32_002 (Mangabeira), from Camp 24. [x1, y1, x2, y2].
PILE_BBOX_ESP32_002 = [480, 60, 920, 340]
PILE_UPSCALE = 2

# How many global frames the screener sees: BEFORE + N mids + AFTER.
N_MIDS = int(os.getenv("SCREENER_N_MIDS", "2"))

OUTPUT_SCHEMA_FIELDS = ["is_real_new_disposal", "pile_delta", "actor_behavior",
                        "confidence_0_100", "reason"]

PILE_DELTA_ENUM = ["increased", "unchanged", "decreased", "unclear"]
ACTOR_ENUM = ["deposited_new", "rummaged_or_took", "passed_by", "none_unclear"]

# ---------------------------------------------------------------------------
# Prompts. The system prompt is shared; the Claude variant adds XML structure
# (refined later from Deep Research DR#1). Both demand the SAME JSON contract.
# ---------------------------------------------------------------------------

SCREENER_SYSTEM_PROMPT = """You are a strict verification agent for an illegal-trash-dumping camera in Mangabeira, Recife. An upstream model already flagged this event as a possible NEW illegal disposal. Your ONLY job is to catch its FALSE ALARMS.

The camera is fixed and points at a sidewalk that ALWAYS has a chronic, pre-existing pile of garbage. The upstream model frequently CONFABULATES a disposal: it sees a person near the pile and claims "they deposited waste / the pile grew", when in reality the person only RUMMAGED through, SORTED, or PICKED FROM the existing pile (a "catador"/waste-picker), or merely PASSED BY.

You must decide, by comparing the BEFORE and AFTER frames, whether NEW waste was actually left on the ground:

- is_real_new_disposal = true  ONLY IF new material is clearly present in the AFTER frame that was NOT there in the BEFORE frame AND it REMAINS after the person leaves (the pile genuinely grew).
- is_real_new_disposal = false IF the person rummaged/handled/took from the existing pile with no net new material, OR only passed by, OR nothing relevant changed.

KEY RULES:
1. The pile being large or present is NOT evidence of a new disposal — it is always there. Judge only the CHANGE between before and after.
2. A person crouching, standing, opening bags, or handling the pile is NOT a disposal unless new material remains afterward.
3. Someone carrying a bag AWAY (or the pile shrinking) is a waste-picker, not a disposer -> false.
4. RECALL GUARD: real disposals must NOT be missed. If you genuinely cannot tell whether new material remained (e.g. a small dark bag, occlusion, night glare), DEFAULT to is_real_new_disposal = true. Only mark false when you are reasonably confident no new material was added."""

SCREENER_TASK_INSTRUCTION = """Compare the frames and return your verdict as a JSON object with EXACTLY these keys:
- "is_real_new_disposal": boolean (false => this is a false alarm to suppress)
- "pile_delta": one of ["increased","unchanged","decreased","unclear"] (did the pile change between before and after?)
- "actor_behavior": one of ["deposited_new","rummaged_or_took","passed_by","none_unclear"]
- "confidence_0_100": integer (your confidence in the is_real_new_disposal value)
- "reason": one short sentence citing the concrete visual evidence (e.g. "white bag in after-frame absent in before" or "person crouches then leaves, pile identical")

Output ONLY the JSON object, no markdown, no extra text."""


# ---------------------------------------------------------------------------
# Haiku 4.5 (Bedrock) tuned variant — from Deep Research DR#1 (2026-06-19):
#   - forensic-analyst persona + <rules> with asymmetric recall guard
#   - XML-interleaved <frame> markers (temporal anchoring)
#   - native structured output via output_config json_schema (fallback: prompted)
#   - extended thinking budget 1024, max_tokens 2048, NO temperature/prefill
# ---------------------------------------------------------------------------

HAIKU_SYSTEM_PROMPT = """You are a forensic CCTV verification analyst for a public-sanitation illegal-dumping monitor in Mangabeira, Recife. A static upstream sensor flagged a possible NEW illegal trash disposal. You are the FINAL authority deciding whether a genuine NEW disposal occurred, versus a FALSE POSITIVE caused by internal sorting of the existing pile (a "catador"/waste-picker) or by mere passers-by. The camera is fixed and the sidewalk ALWAYS has a chronic pre-existing pile — its mere presence is NOT evidence.

<rules>
1. Reorganizing, dismantling, opening, or fragmentary collection of the EXISTING pile (picking/recycling WITHOUT a compensating addition of mass) is NOT a new disposal -> is_real_new_disposal=false.
2. Someone carrying material AWAY, or the pile shrinking/unchanged, is a waste-picker -> false.
3. is_real_new_disposal=true ONLY if material clearly NOT present in the BEFORE frame appears and REMAINS in the AFTER frame (the pile genuinely grew).
4. PRESERVE OPERATIONAL RECALL (asymmetric cost): wrongly rejecting a real disposal degrades the safety net. Under any ambiguity — image degradation, occlusion, night glare, or if the likelihood of added accumulation is above ~15% — the positive verdict (true) is mandatory.
5. Base your differential conclusion on the change between the baseline (BEFORE) and the post-departure (AFTER) frame; use the middle frame only to track the person's hands/behavior, and the ROI crop for fine geometry of small bags.
</rules>"""

# JSON schema shared by Gemini (response_schema) and Bedrock (output_config)
OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning_delta": {"type": "string",
            "description": "Short differential analysis comparing material accumulation in the AFTER frame vs the BEFORE frame; cite the ROI crop for small-bag detail."},
        "actor_behavior": {"type": "string", "enum": ACTOR_ENUM,
            "description": "Person interaction: deposited_new vs rummaged_or_took vs passed_by vs none_unclear."},
        "pile_delta": {"type": "string", "enum": PILE_DELTA_ENUM,
            "description": "Did the pile change between before and after?"},
        "confidence_0_100": {"type": "integer",
            "description": "Certainty [0-100] that NEW material was added and remained."},
        "is_real_new_disposal": {"type": "boolean",
            "description": "Decision. MUST be true if the likelihood of added accumulation exceeds the ~15% safety margin or under any ambiguity (recall guard)."},
        "reason": {"type": "string", "description": "One short sentence citing the concrete visual evidence."},
    },
    "required": ["reasoning_delta", "actor_behavior", "pile_delta", "confidence_0_100", "is_real_new_disposal", "reason"],
    "additionalProperties": False,
}


SCREENER_INTRO = (
    "An upstream model flagged this esp32_002 (Mangabeira) event as a possible NEW "
    "illegal disposal. Below are chronological frames from the event, each preceded "
    "by a label marking its temporal position. Anchor each image to its timestamp, "
    "compare the BEFORE state to the AFTER state, and decide whether new waste was "
    "actually left behind."
)


def build_user_text(frame_labels: list[str]) -> str:
    """frame_labels describe the images in the order they are attached."""
    lines = ["Images attached, in order:"]
    for i, lab in enumerate(frame_labels, 1):
        lines.append(f"  {i}. {lab}")
    lines.append("")
    lines.append(SCREENER_TASK_INSTRUCTION)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Frame selection + pile crop
# ---------------------------------------------------------------------------

def select_frames(frames_dir: Path, n_mids: int = N_MIDS) -> list[Path]:
    """Return [first, mid..., last] from a dir of timestamped jpgs."""
    jpgs = sorted(p for p in frames_dir.glob("*.jpg") if p.stat().st_size > 1000)
    if not jpgs:
        return []
    if len(jpgs) <= n_mids + 2:
        return jpgs
    k = n_mids + 2
    idxs = sorted({round(i * (len(jpgs) - 1) / (k - 1)) for i in range(k)})
    return [jpgs[i] for i in idxs]


def make_pile_crop(frame: Path, bbox=PILE_BBOX_ESP32_002, upscale=PILE_UPSCALE) -> bytes:
    """Crop the pile zone and upscale; return JPEG bytes."""
    img = Image.open(frame).convert("RGB")
    x1, y1, x2, y2 = bbox
    # clamp to image bounds
    x2 = min(x2, img.width); y2 = min(y2, img.height)
    crop = img.crop((x1, y1, x2, y2))
    if upscale and upscale != 1:
        crop = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def build_image_payload(frames_dir: Path, with_pile_crop: bool = True):
    """Return (list_of_(bytes,label)) for the screener: before, mids, after,
    + pile crop of before & after."""
    frames = select_frames(frames_dir)
    if not frames:
        return []
    payload = []
    n = len(frames)
    for i, fr in enumerate(frames):
        if i == 0:
            lab = "GLOBAL FRAME — BEFORE (earliest)"
        elif i == n - 1:
            lab = "GLOBAL FRAME — AFTER (latest)"
        else:
            lab = f"GLOBAL FRAME — middle {i}"
        payload.append((fr.read_bytes(), lab))
    if with_pile_crop:
        payload.append((make_pile_crop(frames[0]), "PILE-ZONE CROP (hi-res) — BEFORE"))
        payload.append((make_pile_crop(frames[-1]), "PILE-ZONE CROP (hi-res) — AFTER"))
    return payload


# ---------------------------------------------------------------------------
# Output parsing + decision
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    s, e = t.find("{"), t.rfind("}")
    if s >= 0 and e > s:
        t = t[s:e + 1]
    return json.loads(t)


def normalize_verdict(raw: dict) -> dict:
    v = dict(raw or {})
    v["is_real_new_disposal"] = bool(v.get("is_real_new_disposal", True))
    pd = str(v.get("pile_delta", "unclear")).lower()
    v["pile_delta"] = pd if pd in PILE_DELTA_ENUM else "unclear"
    ab = str(v.get("actor_behavior", "none_unclear")).lower()
    v["actor_behavior"] = ab if ab in ACTOR_ENUM else "none_unclear"
    try:
        v["confidence_0_100"] = max(0, min(100, int(v.get("confidence_0_100", 50))))
    except Exception:
        v["confidence_0_100"] = 50
    v["reason"] = str(v.get("reason", ""))[:400]
    return v


def decision_keep(verdict: dict) -> bool:
    """True => KEEP (real disposal). False => KILL (suppress false positive)."""
    return bool(verdict.get("is_real_new_disposal", True))
