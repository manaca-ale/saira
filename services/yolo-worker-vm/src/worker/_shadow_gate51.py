"""SHADOW Camp 51 Fase B — dois gates candidatos + `kimi-k2.5` no detail. Log-only.

Os modelos 2.5 de produção são depreciados em outubro/2026 e ainda não há substituto
validado. O Camp 49 concluiu que o detail é substituível e o GATE não; o Camp 51 fechou
a Fase A no dataset e deixou pendente a pergunta que só o tráfego real responde: **qual
a taxa de passagem ABSOLUTA de cada gate candidato**. Sem ela o custo da arquitetura é
condicional, porque cada evento que passa custa uma chamada de kimi (~US$ 0,0064) — 25x
o custo do próprio gate.

Dois braços sobre a MESMA janela e os MESMOS bytes:
  A) `gemini-3.1-flash-lite` + prompt g3  — recupera 6 dos 7 TPs que a prod perde (Camp 51)
  B) `magistral-small` (Bedrock) + prompt g3 — único gate com 30/30 TPs medido (Camp 48)

O detail roda UMA vez por janela se QUALQUER braço disparar, e o resultado é atribuído a
todos os que dispararam: mesma janela e mesmo prompt, chamar duas vezes gastaria o dobro
sem gerar informação nova.

IRMÃO de `_run_shadow_model`/`_run_shadow_bedrock`, não uma generalização delas — mexer no
caminho de produção para acomodar um shadow arriscaria o que já funciona.

Três decisões de método que campanhas anteriores pagaram caro para aprender:

1. **Prompt `g3` no gate, nunca V1 nem V4.** No magistral: V1=93%, g3=100%, **V4=26%**.
   Como o detail usa V4, é fácil vazar o prompt errado para o gate.
2. **Bytes idênticos nos dois braços.** Codifica-se uma vez (640px q70) e os mesmos blobs
   vão para Bedrock e Gemini. O Camp 49 mandou original ao Gemini e low ao Bedrock — isso
   mede resolução, não modelo.
3. **Registra as DUAS regras de decisão**: `fire_raw` (o que o prompt decidiu) e `fire_v1`
   (após a pós-regra determinística de produção). Sem isso não se separa "o modelo errou"
   de "a pós-regra matou o acerto do modelo".
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from . import config
from . import detector_bedrock
from . import detector_gemini as _dg
from . import event_windows
from ._prompts_g3 import G3_GATE_PROMPT
from ._prompts_v4picam import V4_DETAIL_PROMPT
from .detector_gemini import ModelOverride, analyze_new_litter_with_gemini
from .schemas_gemini import GeminiInfractionReport, GeminiNewLitterReport

logger = logging.getLogger(__name__)
BRASILIA = ZoneInfo("America/Sao_Paulo")

# Breaker próprio: estado separado do shadow Bedrock existente para que um não
# silencie o outro.
_BREAKER = {"fails": 0, "open_until": 0.0}


def apply_v1_gate(report):
    """Pós-regra determinística de produção, PURA (sem log, sem efeito colateral).

    Cópia deliberada de `detector_gemini.analyze_new_litter_with_gemini` (ramo `else`,
    "V1 original gate"): extrair a lógica de lá mexeria no caminho de produção por conta
    de um shadow. Os scripts de bench dos camps 48/49/51 fazem a mesma cópia.

    Devolve um objeto com os campos já ajustados — nunca muta o `report` recebido.
    """
    out = report.model_copy(deep=True) if hasattr(report, "model_copy") else report
    scene = (getattr(out, "scene_type", "") or "").upper().strip()

    if scene != "DUMPING" and out.new_litter_detected:
        out.new_litter_detected = False
        out.confidence_0_100 = 0

    bool_count = sum([
        bool(getattr(out, "vehicle_stopped", False)),
        bool(getattr(out, "person_handling_material", False)),
        bool(getattr(out, "new_ground_material", False)),
    ])

    if out.new_litter_detected and bool_count < 2:
        out.new_litter_detected = False
        out.confidence_0_100 = 0

    if not out.new_litter_detected and scene == "DUMPING" and bool_count >= 2:
        out.new_litter_detected = True
        out.confidence_0_100 = max(int(out.confidence_0_100 or 0), 85)

    return out


# ── teto diário de gasto ──────────────────────────────────────────────────────
def _budget_path(day: str) -> Path:
    return Path(config.STATE_DIR) / "shadow_c51_budget" / f"{day}.json"


def _budget_spent(day: str) -> float:
    """Gasto acumulado do dia. Persistido para sobreviver a restart do worker."""
    try:
        p = _budget_path(day)
        if p.is_file():
            return float(json.loads(p.read_text(encoding="utf-8")).get("usd", 0.0))
    except Exception:
        logger.exception("shadow_c51: falha lendo orçamento do dia %s", day)
    return 0.0


def _budget_add(day: str, usd: float) -> None:
    try:
        p = _budget_path(day)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"usd": round(_budget_spent(day) + usd, 8)}),
                     encoding="utf-8")
    except Exception:
        logger.exception("shadow_c51: falha gravando orçamento do dia %s", day)


def _append_audit(device_id: str, record: dict[str, Any]) -> None:
    try:
        day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
        day_dir = Path(config.STATE_DIR) / "shadow_c51_audit" / day
        day_dir.mkdir(parents=True, exist_ok=True)
        with (day_dir / f"{device_id}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.exception("shadow_c51: falha ao gravar audit device=%s", device_id)


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
        logger.warning("shadow_c51: breaker ABERTO por %ds após falhas consecutivas",
                       config.SHADOW_BEDROCK_BREAKER_COOLDOWN_S)


def _gate_mids(win: list[Path]) -> list[Path]:
    """1º + N mids even-spaced + último — mesma seleção da prod e do bench_gate51."""
    n = len(win)
    mid_count = max(0, config.SHADOW_C51_GATE_MIDS)
    if n < 3 or mid_count == 0:
        return []
    step = (n - 1) / (mid_count + 1)
    ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
    return [win[k] for k in ks if 0 < k < n - 1]


def _blobs_as_named_files(blobs: list[bytes], names: list[str], tmpdir: Path) -> list[Path]:
    """Materializa os blobs JÁ codificados preservando o nome original do frame.

    O nome importa: `analyze_new_litter_with_gemini` monta o user prompt a partir de
    `path.name`, e um nome temporário faria o modelo referenciar um frame inexistente.
    """
    out: list[Path] = []
    for blob, name in zip(blobs, names):
        p = tmpdir / name
        p.write_bytes(blob)
        out.append(p)
    return out


def _arm_gemini(gframes: list[Path], cam_ctx: dict, camera, device_id: str,
                log_call) -> dict[str, Any]:
    """Braço A — Gemini no cliente dedicado (custo isolado do projeto de produção)."""
    client = _dg._get_shadow_client()
    if client is None:
        return {"error": "sem cliente shadow dedicado (SHADOW_GEMINI_API_KEY/SHADOW_GCP_PROJECT)"}

    gid = str(uuid4())
    ov = ModelOverride(model=config.SHADOW_C51_GATE_A,
                       thinking_level=config.SHADOW_MODEL_THINKING,
                       media_resolution=config.SHADOW_MODEL_MEDIA_RES,
                       max_output_tokens=config.SHADOW_MODEL_MAX_OUTPUT_TOKENS,
                       client=client)
    res = analyze_new_litter_with_gemini(
        first_frame=gframes[0], last_frame=gframes[-1], camera_context=cam_ctx,
        request_id=gid, prior_window_context=None, use_mosaic=False,
        mid_frames=(gframes[1:-1] or None),
        prompt_version=config.SHADOW_C51_GATE_PROMPT, override=ov)

    # NOTA: o wrapper já aplicou a pós-regra V1 internamente (o ramo `g3` cai no `else`),
    # então o report que volta É o `fire_v1`. O `fire_raw` do Gemini não é observável
    # daqui sem duplicar a chamada — registramos os dois campos com o mesmo valor e
    # marcamos `raw_observable=False` para não induzir leitura errada na análise.
    rep = res.report
    if log_call is not None:
        log_call(camera=camera, device_id=device_id, agent="shadow_c51_gate_a",
                 model=res.model, request_id=gid, usage=res.usage,
                 latency_ms=res.latency_ms, success=True)
    return _arm_record(rep, model=res.model, prompt=config.SHADOW_C51_GATE_PROMPT,
                       tok_in=res.usage.input_tokens, tok_out=res.usage.output_tokens,
                       tok_think=res.usage.thinking_tokens,
                       cost=float(res.usage.estimated_cost_usd or 0.0),
                       latency_ms=res.latency_ms, json_valid=True, error="",
                       raw_observable=False, post_rule_applied=True)


def _arm_bedrock(blobs: list[bytes], guser: str) -> dict[str, Any]:
    """Braço B — magistral-small via Bedrock, com os MESMOS bytes do braço A."""
    alias = config.SHADOW_C51_GATE_B
    res = detector_bedrock.converse(
        alias, G3_GATE_PROMPT, guser, blobs, GeminiNewLitterReport,
        max_tokens=config.SHADOW_BEDROCK_MAX_OUTPUT_TOKENS,
        # vários modelos ACEITAM toolConfig e o IGNORAM, devolvendo `confidence` em vez
        # de `confidence_0_100` — armadilha do Camp 48.
        force_mode="text")
    _breaker_note(ok=not res.error)

    model = (detector_bedrock.MODELS[alias].model_id
             if alias in detector_bedrock.MODELS else alias)
    if not res.json_valid or res.report is None:
        return {"model": model, "prompt": config.SHADOW_C51_GATE_PROMPT,
                "json_valid": False, "error": (res.error or "json inválido")[:250],
                "cost_usd": round(res.cost_usd, 8), "latency_ms": res.latency_ms,
                "tok_in": res.tok_in, "tok_out": res.tok_out,
                "fire_raw": False, "fire_v1": False}
    return _arm_record(res.report, model=model, prompt=config.SHADOW_C51_GATE_PROMPT,
                       tok_in=res.tok_in, tok_out=res.tok_out, tok_think=0,
                       cost=res.cost_usd, latency_ms=res.latency_ms,
                       json_valid=True, error="", raw_observable=True,
                       post_rule_applied=False)


def _arm_record(rep, *, model: str, prompt: str, tok_in: int, tok_out: int,
                tok_think: int, cost: float, latency_ms: int, json_valid: bool,
                error: str, raw_observable: bool, post_rule_applied: bool) -> dict[str, Any]:
    """Monta o registro de um braço, com as DUAS regras de decisão."""
    thr = config.SHADOW_C51_TRIGGER_THR
    conf_raw = int(getattr(rep, "confidence_0_100", 0) or 0)
    fire_raw = bool(getattr(rep, "new_litter_detected", False)) and conf_raw >= thr

    if post_rule_applied:
        # o wrapper de prod já aplicou o pós-gate; o report recebido é o pós-regra
        v1, conf_v1, fire_v1 = rep, conf_raw, fire_raw
    else:
        v1 = apply_v1_gate(rep)
        conf_v1 = int(getattr(v1, "confidence_0_100", 0) or 0)
        fire_v1 = bool(getattr(v1, "new_litter_detected", False)) and conf_v1 >= thr

    return {
        "model": model, "prompt": prompt, "json_valid": json_valid, "error": error,
        "fire_raw": fire_raw, "conf_raw": conf_raw,
        "fire_v1": fire_v1, "conf_v1": conf_v1,
        "raw_observable": raw_observable,
        "scene_type": (getattr(rep, "scene_type", "") or "").upper().strip(),
        "b_vehicle": bool(getattr(rep, "vehicle_stopped", False)),
        "b_person": bool(getattr(rep, "person_handling_material", False)),
        "b_ground": bool(getattr(rep, "new_ground_material", False)),
        "evidence": (getattr(rep, "evidence_summary", "") or "")[:600],
        "tok_in": tok_in, "tok_out": tok_out, "tok_think": tok_think,
        "cost_usd": round(float(cost or 0.0), 8), "latency_ms": latency_ms,
    }


def run(window_paths: list[Path], device_id: str, camera, manifest,
        prod_disposal: bool, prod_detection_id: Optional[str],
        log_call=None) -> None:
    """Roda os dois braços + detail compartilhado. NUNCA cria detecção nem quebra prod."""
    if not config.SHADOW_C51_ENABLED or device_id not in config.SHADOW_C51_DEVICES:
        return
    if _breaker_open():
        return

    day = datetime.now(BRASILIA).strftime("%Y-%m-%d")
    spent = _budget_spent(day)
    if spent >= config.SHADOW_C51_DAILY_BUDGET_USD:
        # Silenciar sem avisar faria os dados parecerem completos quando não estão.
        logger.warning(
            json.dumps({"event": "shadow_c51_budget_exhausted", "device_id": device_id,
                        "day": day, "spent_usd": round(spent, 5),
                        "cap_usd": config.SHADOW_C51_DAILY_BUDGET_USD,
                        "event_ref": getattr(manifest, "event_id", None)}))
        return

    tmpdir: Optional[Path] = None
    try:
        win = event_windows.fit_frames_to_payload(
            list(window_paths), config.GEMINI_MAX_PAYLOAD_BYTES)
        if len(win) < 2:
            return

        gframes = [win[0]] + _gate_mids(win) + [win[-1]]
        # Codifica UMA vez; os mesmos bytes vão para os dois braços.
        pay = detector_bedrock.prepare_images(gframes, mode="low")
        if pay.n_dropped:
            gframes = detector_bedrock._even_drop(gframes, pay.n_images)

        cam_ctx = _shadow_ctx(camera, device_id, win[-1].name)
        guser = _dg._new_litter_user_prompt(
            first_frame_name=gframes[0].name, last_frame_name=gframes[-1].name,
            camera_context=cam_ctx, prior_window_context=None, mosaic=False,
            mid_frame_names=[p.name for p in gframes[1:-1]])

        tmpdir = Path(tempfile.mkdtemp(prefix="c51gate_"))
        gem_frames = _blobs_as_named_files(pay.blobs, [p.name for p in gframes], tmpdir)

        # Os dois gates em paralelo: o worker é sequencial e somar latências viraria
        # backlog na fila de eventos. SHADOW_C51_GATE_B vazio/"off" desliga só o braço B
        # (revisão de 11/08: o magistral dispara 3,4x mais que o A e paga 74% do detail).
        b_off = config.SHADOW_C51_GATE_B.strip().lower() in ("", "off", "none", "disabled")
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(_arm_gemini, gem_frames, cam_ctx, camera, device_id, log_call)
            fb = None if b_off else pool.submit(_arm_bedrock, pay.blobs, guser)
            arm_a = _safe(fa, "a")
            arm_b = _ARM_B_DISABLED if fb is None else _safe(fb, "b")

        triggered_by = [k for k, a in (("a", arm_a), ("b", arm_b)) if a.get("fire_v1")]

        detail: dict[str, Any] = {"ran": False, "triggered_by": triggered_by}
        if triggered_by:
            dpay = detector_bedrock.prepare_images(win, mode="low")
            names = [p.name for p in win]
            if dpay.n_dropped:
                names = [p.name for p in detector_bedrock._even_drop(win, dpay.n_images)]
            duser = _dg._user_prompt(camera_context=cam_ctx, frame_names=names,
                                     mosaic_mode="off", prior_window_context=None)
            dres = detector_bedrock.converse(
                config.SHADOW_C51_DETAIL_ALIAS, V4_DETAIL_PROMPT, duser, dpay.blobs,
                GeminiInfractionReport,
                max_tokens=config.SHADOW_BEDROCK_MAX_OUTPUT_TOKENS, force_mode="text")
            _breaker_note(ok=not dres.error)
            drep = dres.report
            detail.update({
                "ran": True, "alias": config.SHADOW_C51_DETAIL_ALIAS,
                "n_images": dpay.n_images, "n_dropped": dpay.n_dropped,
                "payload_mb": round(dpay.raw_bytes / 1e6, 3),
                "would_confirm": bool(getattr(drep, "infraction_confirmed", False)) if drep else False,
                "conf": int(getattr(drep, "confidence_0_100", 0) or 0) if drep else None,
                "waste_type": getattr(drep, "waste_type", None) if drep else None,
                "offender_detected": bool(getattr(drep, "offender_detected", False)) if drep else None,
                "evidence": ((getattr(drep, "evidence_summary", "") or "")[:1000] if drep else ""),
                "json_valid": bool(dres.json_valid),
                "cost_usd": round(dres.cost_usd, 8), "latency_ms": dres.latency_ms,
                "error": dres.error,
            })

        total_cost = (float(arm_a.get("cost_usd") or 0.0)
                      + float(arm_b.get("cost_usd") or 0.0)
                      + float(detail.get("cost_usd") or 0.0))
        _budget_add(day, total_cost)

        rec = {
            "event_ref": getattr(manifest, "event_id", None),
            "ts": datetime.now(BRASILIA).isoformat(), "device_id": device_id,
            "window_first": win[0].name, "window_last": win[-1].name,
            "window_size": len(win), "gate_n_images": pay.n_images,
            "gate_payload_mb": round(pay.raw_bytes / 1e6, 3),
            "arm_a": arm_a, "arm_b": arm_b, "detail": detail,
            "total_cost_usd": round(total_cost, 8),
            "prod_created_detection": bool(prod_disposal),
            "prod_detection_id": prod_detection_id,
        }
        _append_audit(device_id, rec)
        logger.info(json.dumps({
            "event": "shadow_c51", "device_id": device_id,
            "event_ref": rec["event_ref"],
            "a_fire": arm_a.get("fire_v1"), "b_fire": arm_b.get("fire_v1"),
            "detail_ran": detail["ran"], "detail_confirm": detail.get("would_confirm"),
            "prod_disposal": bool(prod_disposal),
            "cost_usd": rec["total_cost_usd"],
            "day_spent_usd": round(_budget_spent(day), 5),
            "a_err": arm_a.get("error", ""), "b_err": arm_b.get("error", ""),
        }, ensure_ascii=False))
    except Exception:
        logger.exception("shadow_c51 failed device=%s event=%s", device_id,
                         getattr(manifest, "event_id", None))
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


# Registro imutável do braço B desligado: mantém o schema do ledger (fire_v1 False
# nunca dispara o detail) e o custo zerado fora da soma do orçamento diário.
_ARM_B_DISABLED = {"model": "disabled", "prompt": "", "json_valid": True, "error": "",
                   "fire_raw": False, "fire_v1": False, "disabled": True,
                   "tok_in": 0, "tok_out": 0, "cost_usd": 0.0, "latency_ms": 0}


def _safe(future, tag: str) -> dict[str, Any]:
    """Um braço que falha não pode derrubar o outro nem o registro da janela."""
    try:
        return future.result()
    except Exception as exc:
        logger.exception("shadow_c51: braço %s falhou", tag)
        return {"error": f"{type(exc).__name__}: {exc}"[:250],
                "fire_raw": False, "fire_v1": False, "cost_usd": 0.0}


def _shadow_ctx(camera, device_id: str, last_frame_name: str) -> dict[str, str]:
    """Mesmo contexto de câmera dos shadows irmãos (import tardio evita ciclo)."""
    from .main import _shadow_camera_context
    return _shadow_camera_context(camera, device_id, last_frame_name)
