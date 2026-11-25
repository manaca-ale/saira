"""Filtro antes do gate — API de Decisões (`gemini-decision-1`), campanha 54.

Uma chamada por janela, com os MESMOS frames que o gate vai ver, em resolução baixa, e
UMA pergunta (`wl_v2`: "esta sequência merece um olhar mais de perto?"). A resposta é uma
probabilidade; o evento segue para o gate se ela for >= `GATE_PREFILTER_THRESHOLD` (0,30
na medição). É a primeira etapa dos dois funis finalistas da campanha 54
(`benchmarks/campaigns/54-*/results/finalistas54__dev.md`): corta a maior parte das
cenas vazias a US$ 0,0002 por chamada, antes de pagar o gate.

Desligado por padrão (`GATE_PREFILTER_ENABLED=false`) e, quando ligado, em modo só
registro (`GATE_PREFILTER_LOG_ONLY=true`) até alguém pedir que ele barre. Três garantias:

1. **Falha sempre ABERTA**: `evaluate()` nunca levanta exceção. Sem chave, erro HTTP,
   timeout, resposta sem a nota, disjuntor aberto ou teto do dia estourado = o evento
   segue para o gate, como hoje.
2. **Cliente isolado**: endpoint, chave e modelo vêm de variáveis próprias. O modelo só
   existe na API do AI Studio (v1beta); o caminho Gemini de produção não é tocado.
3. **A chave nunca aparece** em log, auditoria ou `gemini_call_log`.

A chamada é a de `benchmarks/campaigns/53-*/scripts/bench_decisions.py`
(`call_decisions`) com o conjunto `q5` de `benchmarks/campaigns/54-*/scripts/qsets54.py`.
`CONTEXT` e `QUESTIONS` são CÓPIAS literais: mudar uma palavra invalida a medição (a
resposta depende também das outras perguntas do pedido, por isso a pergunta vai sozinha).
"""
from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import config

logger = logging.getLogger(__name__)
BRASILIA = ZoneInfo("America/Sao_Paulo")

_BREAKER = {"fails": 0, "open_until": 0.0}
# 402 (crédito pré-pago esgotado) desliga até o dia seguinte; "sem chave" avisa uma vez.
_STATE: dict[str, Any] = {"disabled_day": None, "warned_no_key": False, "warned_budget_day": None}

CONTEXT = (
    "You are looking at a chronological sequence of frames from ONE fixed CCTV camera aimed at "
    "a known illegal-dumping hotspot on a residential street in Recife, Brazil. A waste pile is "
    "usually already present at the curb: its presence is the normal background and is never by "
    "itself evidence of a new dumping act. Frames are labelled 'Frame k of N' in time order.\n"
)

QUESTION = "wl_v2"
QUESTIONS: dict[str, dict[str, Any]] = {
    "wl_v2": {
        "type": "noul",
        "instructions": (
            "Could this sequence plausibly show someone leaving waste, bags, debris or objects at the "
            "pile or on the ground, so that it deserves a closer look?"),
        "criteria": {
            "true_description": (
                "A person or vehicle stops at or interacts with the pile area, carries or unloads something, or new "
                "material appears on the ground. Also yes when a truck, cart or wheelbarrow is at or backing toward "
                "the pile, or when a person walks up to the pile and walks away, including at night or among other "
                "people and vehicles, even if the unloading itself is not visible."),
            "false_description": (
                "Clearly nothing of the sort: an empty scene, a lighting change, animals, or people and vehicles that "
                "only pass through or stay parked away from the pile."),
        },
    },
}


class DecisionsHTTPError(RuntimeError):
    """Resposta HTTP de erro da API de Decisões (o corpo já vem sem a chave)."""

    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status


@dataclass
class PrefilterResult:
    ran: bool = False                 # a chamada foi feita (com ou sem erro)
    score: Optional[float] = None     # probabilidade de "sim" na pergunta; None = sem nota
    threshold: float = 0.0
    log_only: bool = True
    reason: str = ""                  # por que não rodou ou falhou ("" = rodou e tem nota)
    request_id: str = ""
    tok_in: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    http_status: int = 0
    error: str = ""

    @property
    def below_threshold(self) -> bool:
        return self.score is not None and self.score < self.threshold

    @property
    def should_skip(self) -> bool:
        """True só quando há nota, ela ficou abaixo do limiar e o filtro pode barrar."""
        return self.below_threshold and not self.log_only


def enabled_for(device_id: Optional[str]) -> bool:
    return bool(config.GATE_PREFILTER_ENABLED
                and (device_id or "").strip().lower() in config.GATE_PREFILTER_DEVICES)


# ── teto diário de gasto, auditoria e disjuntor (mesmo desenho dos shadows) ───
def _budget_path(day: str) -> Path:
    return Path(config.STATE_DIR) / "gate_prefilter_budget" / f"{day}.json"


def _budget_spent(day: str) -> float:
    """Gasto acumulado do dia. Persistido para sobreviver a restart do worker."""
    try:
        p = _budget_path(day)
        if p.is_file():
            return float(json.loads(p.read_text(encoding="utf-8")).get("usd", 0.0))
    except Exception:
        logger.exception("gate_prefilter: falha lendo orçamento do dia %s", day)
    return 0.0


def _budget_add(day: str, usd: float) -> None:
    try:
        p = _budget_path(day)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"usd": round(_budget_spent(day) + usd, 8)}),
                     encoding="utf-8")
    except Exception:
        logger.exception("gate_prefilter: falha gravando orçamento do dia %s", day)


def _append_audit(device_id: str, record: dict[str, Any]) -> None:
    try:
        day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
        day_dir = Path(config.STATE_DIR) / "gate_prefilter_audit" / day
        day_dir.mkdir(parents=True, exist_ok=True)
        with (day_dir / f"{device_id}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("gate_prefilter: falha ao gravar audit device=%s", device_id)


def _breaker_open() -> bool:
    return time.time() < _BREAKER["open_until"]


def _breaker_note(ok: bool) -> None:
    if ok:
        _BREAKER["fails"] = 0
        return
    _BREAKER["fails"] += 1
    if _BREAKER["fails"] >= config.GATE_PREFILTER_BREAKER_FAILS:
        _BREAKER["open_until"] = time.time() + config.GATE_PREFILTER_BREAKER_COOLDOWN_S
        _BREAKER["fails"] = 0
        logger.warning("gate_prefilter: breaker ABERTO por %ds após falhas consecutivas",
                       config.GATE_PREFILTER_BREAKER_COOLDOWN_S)


# ── a chamada ─────────────────────────────────────────────────────────────────
def _scrub(text: str) -> str:
    """Tira a chave de qualquer texto que vá para log ou registro."""
    key = config.GATE_PREFILTER_API_KEY
    text = text or ""
    return text.replace(key, "<chave>") if key else text


def build_body(frames: list[Path]) -> dict[str, Any]:
    """Corpo da requisição: contexto, depois `Frame i of n` + imagem para cada frame."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": CONTEXT}]
    n = len(frames)
    for i, p in enumerate(frames, 1):
        blocks.append({"type": "text", "text": f"\nFrame {i} of {n}:\n"})
        blocks.append({"type": "image", "mime_type": "image/jpeg",
                       "resolution": config.GATE_PREFILTER_RESOLUTION,
                       "data": base64.b64encode(Path(p).read_bytes()).decode("ascii")})
    return {"model": config.GATE_PREFILTER_MODEL, "input": blocks, "questions": QUESTIONS}


def _http_post(body: dict[str, Any]) -> dict[str, Any]:
    """Uma tentativa só, com timeout curto: roda antes do gate, na thread do pipeline."""
    req = urllib.request.Request(
        config.GATE_PREFILTER_ENDPOINT, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"x-goog-api-key": config.GATE_PREFILTER_API_KEY,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=config.GATE_PREFILTER_TIMEOUT_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise DecisionsHTTPError(exc.code, _scrub(exc.read().decode("utf-8", "replace"))[:400])


def probability(answers: Any, question: str = QUESTION) -> Optional[float]:
    """Probabilidade de "sim" da pergunta `noul`; None se a resposta não trouxer a nota."""
    try:
        ans = (answers or {}).get(question) or {}
        if "noul" in ans:
            p = float(ans["noul"])
            return p if 0.0 <= p <= 1.0 else None
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


def evaluate(frames: list[Path], device_id: str, event_ref: Optional[str] = None) -> PrefilterResult:
    """Uma chamada ao Decisions com os frames do gate. NUNCA levanta; falha aberta."""
    res = PrefilterResult(threshold=config.GATE_PREFILTER_THRESHOLD,
                          log_only=config.GATE_PREFILTER_LOG_ONLY)
    try:
        if not enabled_for(device_id):
            res.reason = "disabled"
            return res
        if not config.GATE_PREFILTER_API_KEY:
            res.reason = "no_key"
            if not _STATE["warned_no_key"]:
                _STATE["warned_no_key"] = True
                logger.warning(json.dumps({"event": "gate_prefilter_no_key",
                                           "detail": "GATE_PREFILTER_API_KEY vazia; filtro em falha aberta"}))
            return res
        day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
        if _STATE["disabled_day"] == day:
            res.reason = "credit_depleted"
            return res
        if _breaker_open():
            res.reason = "breaker_open"
            return res
        spent = _budget_spent(day)
        if spent >= config.GATE_PREFILTER_DAILY_BUDGET_USD:
            res.reason = "budget_exhausted"
            # Avisa uma vez por dia: em falha aberta o custo do gate volta ao de sem filtro.
            if _STATE["warned_budget_day"] != day:
                _STATE["warned_budget_day"] = day
                logger.warning(json.dumps({
                    "event": "gate_prefilter_budget_exhausted", "device_id": device_id, "day": day,
                    "spent_usd": round(spent, 5), "cap_usd": config.GATE_PREFILTER_DAILY_BUDGET_USD}))
            return res
        frames = [Path(p) for p in frames]
        if len(frames) < 2:
            res.reason = "too_few_frames"
            return res

        res.ran = True
        res.request_id = str(uuid4())
        res.http_status = 200
        t0 = time.time()
        try:
            resp = _http_post(build_body(frames))
            answers = resp.get("answers") if isinstance(resp, dict) else None
            res.tok_in = input_tokens(resp.get("usage")) if isinstance(resp, dict) else 0
            res.score = probability(answers)
            if res.score is None:
                res.error = ("resposta sem answers[%s]: " % QUESTION) + _scrub(
                    json.dumps(resp, ensure_ascii=False))[:300]
        except DecisionsHTTPError as exc:
            res.http_status, res.error = exc.status, str(exc)[:400]
        except Exception as exc:  # noqa: BLE001 — timeout, rede, JSON inválido
            res.http_status, res.error = 0, _scrub(f"{type(exc).__name__}: {exc}")[:300]
        res.latency_ms = int((time.time() - t0) * 1000)
        if res.error:
            res.reason = "error"

        if res.http_status == 402:
            # Crédito pré-pago esgotado: repetir a cada janela só encheria o log.
            _STATE["disabled_day"] = day
            logger.warning(json.dumps({"event": "gate_prefilter_credit_depleted", "day": day,
                                       "detail": "HTTP 402; filtro em falha aberta até o dia seguinte"}))
        else:
            _breaker_note(ok=not res.error)

        res.cost_usd = res.tok_in * config.GATE_PREFILTER_PRICE_IN_PER_1M / 1e6
        if res.cost_usd:
            _budget_add(day, res.cost_usd)
        rec = {
            "event": "gate_prefilter", "event_ref": event_ref,
            "ts": datetime.now(BRASILIA).isoformat(), "device_id": device_id,
            "request_id": res.request_id, "model": config.GATE_PREFILTER_MODEL,
            "resolution": config.GATE_PREFILTER_RESOLUTION, "frames": [p.name for p in frames],
            QUESTION: res.score, "threshold": res.threshold,
            "below_threshold": res.below_threshold, "log_only": res.log_only,
            "skipped_gate": res.should_skip,
            "tok_in": res.tok_in, "cost_usd": round(res.cost_usd, 8),
            "latency_ms": res.latency_ms, "http_status": res.http_status, "error": res.error,
        }
        _append_audit(device_id, rec)
        logger.info(json.dumps(rec, ensure_ascii=False))
    except Exception:
        logger.exception("gate_prefilter failed device=%s event=%s", device_id, event_ref)
        # falha aberta: sem nota, o evento segue para o gate
        res.score = None
        res.reason = res.reason or "exception"
    return res
