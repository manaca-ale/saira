"""SHADOW Camp 53 — gate candidato `gemini-decision-1` (API de Decisões). Log-only.

O Camp 53 mediu o Decisions como gate no dataset: mesmo recall do gate de produção no
conjunto oficial, a um quinto do custo por chamada (US$ 0,00021 contra US$ 0,0011). O que
o dataset não responde é a **taxa de passagem em tráfego real** por limiar, que é o que
fecha a conta de custo da cascata, e a estabilidade da probabilidade ao longo dos dias.

Fase 1 (este módulo): só o gate. Uma chamada por janela, com os MESMOS 5 frames do gate
de produção, e um registro com as probabilidades cruas das seis perguntas — guardar o
valor cru permite reavaliar qualquer limiar depois, sem chamada nova. Nenhum limiar
decide nada; `fire_t*` é só registro. A fase 2 (detail nos eventos que só o Decisions
passa) não está implementada.

IRMÃO de `_shadow_gate51`, não uma generalização dele. Três garantias:

1. **Falha sempre aberta**: `run()` nunca levanta exceção e nunca cria detecção.
2. **Cliente isolado**: endpoint, chave e modelo vêm de variáveis próprias. O modelo só
   existe na API do AI Studio (v1beta); quando o Google liberar no Vertex, troca-se a
   configuração sem tocar no caminho de produção.
3. **A chave nunca aparece** em log, auditoria ou `gemini_call_log`.

A chamada é a mesma de `benchmarks/campaigns/53-*/scripts/bench_decisions.py`
(`call_decisions`, conjunto `q1`, resolução baixa), que foi a medida: 2.097 tokens de
entrada por chamada, zero de saída.
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import config
from . import event_windows
from .models import GeminiUsage

logger = logging.getLogger(__name__)
BRASILIA = ZoneInfo("America/Sao_Paulo")

# Breaker próprio: estado separado dos outros shadows para que um não silencie o outro.
_BREAKER = {"fails": 0, "open_until": 0.0}
# 402 (crédito pré-pago esgotado) desliga até o dia seguinte; "sem chave" avisa uma vez.
_STATE: dict[str, Any] = {"disabled_day": None, "warned_no_key": False}

CONTEXT = (
    "You are looking at a chronological sequence of frames from ONE fixed CCTV camera aimed at "
    "a known illegal-dumping hotspot on a residential street in Recife, Brazil. A waste pile is "
    "usually already present at the curb: its presence is the normal background and is never by "
    "itself evidence of a new dumping act. Frames are labelled 'Frame k of N' in time order.\n"
)

# Conjunto `q1` do Camp 53, CÓPIA literal de `bench_decisions.QSETS["q1"]`: mudar uma palavra
# aqui invalida a comparação com o que foi medido. O modelo não vê as chaves, só `instructions`.
# A decisão de gate medida é `deposit`; as outras cinco custam o mesmo (a entrada é uma só).
GATE_QUESTION = "deposit"
QUESTIONS: dict[str, dict[str, Any]] = {
    "deposit": {
        "type": "noul",
        "instructions": (
            "Within this sequence, does a person or a vehicle occupant ADD waste or material "
            "to the pile or leave it on the ground? This includes a person on foot carrying a "
            "bag or object and placing, dropping or throwing it, and unloading from a car, "
            "truck, cart or wheelbarrow. Answer yes when the deposit act is visible, or when "
            "a new bag/object/material rests on the ground or pile in a later frame, was "
            "absent in the first frame, and an actor was at that spot in between. Answer no "
            "for people or vehicles that only pass through, vehicles parked with nobody "
            "handling material, people who only REMOVE or sort items from the pile, and "
            "changes that are only lighting or shadows."),
    },
    "actor_at_pile": {
        "type": "noul",
        "instructions": (
            "Does any person or vehicle STOP at or right next to the waste pile or deposit "
            "area and interact with it or handle material there, as opposed to only passing "
            "through or staying away from it?"),
    },
    "removal": {
        "type": "noul",
        "instructions": (
            "Is someone taking material AWAY from the pile: a waste picker rummaging, "
            "sorting, bagging or loading a handcart, or a municipal crew or truck collecting "
            "the waste, so that the actor leaves with more than they arrived with?"),
    },
    "pile_grew": {
        "type": "noul",
        "instructions": (
            "Comparing the first frame with the last frame, is there visibly MORE waste, or "
            "a NEW bag or object, on the ground or on the pile in the last frame?"),
    },
    "carrying_in": {
        "type": "noul",
        "instructions": (
            "Does any person arrive holding or carrying a bag, box, sack or other object and "
            "later appear without it, or appear putting it down?"),
    },
    "scene": {
        "type": "choice",
        "instructions": "Which label best describes what happens in this sequence?",
        "criteria": {
            "EMPTY": "No person or vehicle appears.",
            "TRAFFIC": "People or vehicles move through without interacting with the pile.",
            "PARKED": "A vehicle is stationary and nobody handles material at the pile.",
            "COLLECTION": "Someone removes, sorts or collects material from the pile.",
            "DUMPING": "Someone adds waste or material to the pile or leaves it on the ground.",
        },
    },
}


class DecisionsHTTPError(RuntimeError):
    """Resposta HTTP de erro da API de Decisões (o corpo já vem sem a chave)."""

    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status


# ── teto diário de gasto, auditoria e disjuntor (mesmo desenho do shadow do Camp 51) ──
def _budget_path(day: str) -> Path:
    return Path(config.STATE_DIR) / "shadow_decisions_budget" / f"{day}.json"


def _budget_spent(day: str) -> float:
    """Gasto acumulado do dia. Persistido para sobreviver a restart do worker."""
    try:
        p = _budget_path(day)
        if p.is_file():
            return float(json.loads(p.read_text(encoding="utf-8")).get("usd", 0.0))
    except Exception:
        logger.exception("shadow_decisions: falha lendo orçamento do dia %s", day)
    return 0.0


def _budget_add(day: str, usd: float) -> None:
    try:
        p = _budget_path(day)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"usd": round(_budget_spent(day) + usd, 8)}),
                     encoding="utf-8")
    except Exception:
        logger.exception("shadow_decisions: falha gravando orçamento do dia %s", day)


def _append_audit(device_id: str, record: dict[str, Any]) -> None:
    try:
        day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
        day_dir = Path(config.STATE_DIR) / "shadow_decisions_audit" / day
        day_dir.mkdir(parents=True, exist_ok=True)
        with (day_dir / f"{device_id}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("shadow_decisions: falha ao gravar audit device=%s", device_id)


def _breaker_open() -> bool:
    return time.time() < _BREAKER["open_until"]


def _breaker_note(ok: bool) -> None:
    if ok:
        _BREAKER["fails"] = 0
        return
    _BREAKER["fails"] += 1
    if _BREAKER["fails"] >= config.SHADOW_BEDROCK_BREAKER_FAILS:
        _BREAKER["open_until"] = time.time() + config.SHADOW_BEDROCK_BREAKER_COOLDOWN_S
        _BREAKER["fails"] = 0
        logger.warning("shadow_decisions: breaker ABERTO por %ds após falhas consecutivas",
                       config.SHADOW_BEDROCK_BREAKER_COOLDOWN_S)


def _gate_frames(win: list[Path]) -> list[Path]:
    """1º + N mids even-spaced + último — a mesma seleção do gate de produção."""
    n = len(win)
    mid_count = max(0, config.SHADOW_DECISIONS_GATE_MIDS)
    mids: list[Path] = []
    if n >= 3 and mid_count > 0:
        step = (n - 1) / (mid_count + 1)
        ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
        mids = [win[k] for k in ks if 0 < k < n - 1]
    return [win[0]] + mids + [win[-1]]


# ── a chamada ─────────────────────────────────────────────────────────────────
def _scrub(text: str) -> str:
    """Tira a chave de qualquer texto que vá para log ou registro."""
    key = config.SHADOW_DECISIONS_API_KEY
    text = text or ""
    return text.replace(key, "<chave>") if key else text


def build_body(frames: list[Path]) -> dict[str, Any]:
    """Corpo da requisição: contexto, depois `Frame i of n` + imagem para cada frame."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": CONTEXT}]
    n = len(frames)
    for i, p in enumerate(frames, 1):
        blocks.append({"type": "text", "text": f"\nFrame {i} of {n}:\n"})
        blocks.append({"type": "image", "mime_type": "image/jpeg",
                       "resolution": config.SHADOW_DECISIONS_RESOLUTION,
                       "data": base64.b64encode(p.read_bytes()).decode("ascii")})
    return {"model": config.SHADOW_DECISIONS_MODEL, "input": blocks, "questions": QUESTIONS}


def _http_post(body: dict[str, Any]) -> dict[str, Any]:
    """Uma tentativa só, com timeout curto: é shadow, não vale segurar o worker."""
    req = urllib.request.Request(
        config.SHADOW_DECISIONS_ENDPOINT, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"x-goog-api-key": config.SHADOW_DECISIONS_API_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=config.SHADOW_DECISIONS_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise DecisionsHTTPError(exc.code, _scrub(exc.read().decode("utf-8", "replace"))[:400])


def probability(answers: dict[str, Any], question: str) -> Optional[float]:
    """Probabilidade de "sim" (`noul`) ou, na pergunta de escolha, de `DUMPING`."""
    ans = (answers or {}).get(question) or {}
    try:
        if "noul" in ans:
            return float(ans["noul"])
        probs = ans.get("probabilities")
        if isinstance(probs, dict) and "DUMPING" in probs:
            return float(probs["DUMPING"])
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def input_tokens(usage: Any) -> int:
    """Tokens de entrada do campo `usage`; o formato varia, então aceita as chaves vistas."""
    if not isinstance(usage, dict):
        return 0
    for k in ("total_input_tokens", "input_tokens", "prompt_token_count", "total_tokens",
              "totalInputTokens", "inputTokens", "promptTokenCount", "totalTokens"):
        v = usage.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return int(v)
    return 0


def _fire_fields(p: Optional[float]) -> dict[str, bool]:
    return {f"fire_t{int(round(thr * 100)):02d}": bool(p is not None and p >= thr)
            for thr in config.SHADOW_DECISIONS_THRESHOLDS}


def run(window_paths: list[Path], device_id: str, camera, manifest,
        prod_disposal: bool, prod_detection_id: Optional[str],
        log_call=None, prod_gate_triggered: Optional[bool] = None,
        prod_gate_confidence: Optional[int] = None) -> None:
    """Uma chamada ao Decisions por janela. NUNCA cria detecção nem quebra prod."""
    try:
        if not config.SHADOW_DECISIONS_ENABLED or device_id not in config.SHADOW_DECISIONS_DEVICES:
            return
        if not config.SHADOW_DECISIONS_API_KEY:
            if not _STATE["warned_no_key"]:
                _STATE["warned_no_key"] = True
                logger.warning(json.dumps({"event": "shadow_decisions_no_key",
                                           "detail": "SHADOW_DECISIONS_API_KEY vazia; shadow desligado"}))
            return
        day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
        if _STATE["disabled_day"] == day or _breaker_open():
            return
        spent = _budget_spent(day)
        if spent >= config.SHADOW_DECISIONS_DAILY_BUDGET_USD:
            # Silenciar sem avisar faria os dados parecerem completos quando não estão.
            logger.warning(
                json.dumps({"event": "shadow_decisions_budget_exhausted", "device_id": device_id,
                            "day": day, "spent_usd": round(spent, 5),
                            "cap_usd": config.SHADOW_DECISIONS_DAILY_BUDGET_USD,
                            "event_ref": getattr(manifest, "event_id", None)}))
            return

        win = event_windows.fit_frames_to_payload(
            list(window_paths), config.GEMINI_MAX_PAYLOAD_BYTES)
        if len(win) < 2:
            return
        frames = _gate_frames(win)

        request_id = str(uuid4())
        answers: dict[str, Any] = {}
        tok_in, status, error = 0, 200, ""
        t0 = time.time()
        try:
            resp = _http_post(build_body(frames))
            answers = resp.get("answers") if isinstance(resp, dict) else None
            tok_in = input_tokens(resp.get("usage")) if isinstance(resp, dict) else 0
            if not isinstance(answers, dict) or probability(answers, GATE_QUESTION) is None:
                error = "resposta sem answers[deposit]: " + _scrub(json.dumps(resp, ensure_ascii=False))[:300]
                answers = answers if isinstance(answers, dict) else {}
        except DecisionsHTTPError as exc:
            status, error = exc.status, str(exc)[:400]
        except Exception as exc:  # noqa: BLE001 — timeout, rede, JSON inválido
            status, error = 0, _scrub(f"{type(exc).__name__}: {exc}")[:300]
        latency_ms = int((time.time() - t0) * 1000)

        if status == 402:
            # Crédito pré-pago esgotado: repetir a cada janela só encheria o log.
            _STATE["disabled_day"] = day
            logger.warning(json.dumps({"event": "shadow_decisions_credit_depleted", "day": day,
                                       "detail": "HTTP 402; shadow desligado até o dia seguinte"}))
        else:
            _breaker_note(ok=not error)

        cost = tok_in * config.SHADOW_DECISIONS_PRICE_IN_PER_1M / 1e6
        if cost:
            _budget_add(day, cost)
        p_gate = probability(answers, GATE_QUESTION)
        rec = {
            "event_ref": getattr(manifest, "event_id", None),
            "ts": datetime.now(BRASILIA).isoformat(), "device_id": device_id,
            "camera_id": getattr(camera, "id", None), "request_id": request_id,
            "model": config.SHADOW_DECISIONS_MODEL,
            "resolution": config.SHADOW_DECISIONS_RESOLUTION,
            "window_size": len(win), "frames": [p.name for p in frames],
            "probabilities": {q: probability(answers, q) for q in QUESTIONS},
            "scene": (answers.get("scene") or {}).get("probabilities")
            if isinstance(answers.get("scene"), dict) else None,
            GATE_QUESTION: p_gate, **_fire_fields(p_gate),
            "prod_gate_triggered": prod_gate_triggered,
            "prod_gate_confidence": prod_gate_confidence,
            "prod_created_detection": bool(prod_disposal),
            "prod_detection_id": prod_detection_id,
            "tok_in": tok_in, "cost_usd": round(cost, 8), "latency_ms": latency_ms,
            "http_status": status, "error": error,
        }
        _append_audit(device_id, rec)
        if log_call is not None:
            log_call(camera=camera, device_id=device_id, agent="shadow_decisions_gate",
                     model=config.SHADOW_DECISIONS_MODEL, request_id=request_id,
                     usage=GeminiUsage(input_tokens=tok_in, total_tokens=tok_in,
                                       estimated_cost_usd=cost),
                     latency_ms=latency_ms, success=not error,
                     error_message=(error or None))
        logger.info(json.dumps({
            "event": "shadow_decisions", "device_id": device_id, "event_ref": rec["event_ref"],
            GATE_QUESTION: p_gate, **_fire_fields(p_gate),
            "prod_gate_triggered": prod_gate_triggered, "prod_disposal": bool(prod_disposal),
            "cost_usd": rec["cost_usd"], "latency_ms": latency_ms, "error": error,
        }, ensure_ascii=False))
    except Exception:
        logger.exception("shadow_decisions failed device=%s event=%s", device_id,
                         getattr(manifest, "event_id", None))
