#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — candidatos a detail nas janelas em que os gates disparam (missao 5).

Chama o detail do worker (mesmo codigo de producao, via bench53) com a janela completa do evento
(sample.csv, coluna window; limites do worker: GEMINI_CASCADE_MAX_FRAMES e GEMINI_MAX_PAYLOAD_BYTES),
trocando por braco: modelo, thinking, resolucao da imagem, prompt e numero de frames.

Fiel ao caminho de producao (main.py, _process_with_gemini), ao contrario do bench53 da campanha 53:
  - o detail recebe o MESMO aviso da janela anterior que o gate ("Prior window context"), reconstruido
    pela contagem de tokens do gate de producao (run_gate54.prior_contexts);
  - o camera_context NAO leva horario_local (so o gate leva).
O braco d25f_v1_c53 repete o modo da campanha 53 (sem aviso, com horario) so para a sonda de tokens.

Paga pela carteira `aistudio` (trava bench_budget), um braco por execucao. Sempre --dry-run antes.
So o conjunto de DESENVOLVIMENTO (nao ha opcao para o de avaliacao). Conjunto (--set):
  fires   uniao dos eventos do `pass` em que algum gate de referencia dispara (r1 e r2 de
          g25l_v1_t2048_ctx, g31l_v1p_min_low_ctx e nvl_v1p_low_ctx), com a janela inteira em disco
--subs filtra por estrato (S2C,S2R,S2X,S1,S0); --pick N sorteia N por estrato (hash fixo).

Uso:
  python run_detail54.py --arm d25f_v1 --flex --dry-run
  python run_detail54.py --arm d25f_v1 --flex --max-usd 1.00
Saida: ../results/detail54__<braco>__r<rep>.jsonl (um registro por evento; retoma de onde parou).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4

import run_gate54 as g54
from run_gate54 import RESULTS, b, cost_usd, Budget

GATE_REFS = ("g25l_v1_t2048_ctx", "g31l_v1p_min_low_ctx", "nvl_v1p_low_ctx")
FLEX_TIMEOUT_S = 600

# est = custo estimado por chamada a preco padrao do AI Studio (US$), janela mediana de 32 frames.
ARMS = {
    # controle: o detail de hoje
    "d25f_v1": {"model": "gemini-2.5-flash", "prompt": "v1", "est": 0.012},
    "d25f_v1_c53": {"model": "gemini-2.5-flash", "prompt": "v1", "prior": "off", "horario": True,
                    "est": 0.012},
    # recomendacao da campanha 53 (medida la sem o aviso)
    "d38f_g3_low_low": {"model": "gemini-3.8-flash", "prompt": "g3", "think": "low", "media": "low",
                        "est": 0.008},
    "d38f_v1_low_low": {"model": "gemini-3.8-flash", "prompt": "v1", "think": "low", "media": "low",
                        "est": 0.008},
    "d38f_v4_low_low": {"model": "gemini-3.8-flash", "prompt": "v4", "think": "low", "media": "low",
                        "est": 0.008},
    # para onde a producao e roteada em 01/12 se ninguem mexer (padroes do modelo)
    "d35l_v1_routed": {"model": "gemini-3.5-flash-lite", "prompt": "v1", "est": 0.022},
    "d35l_v1_low_high": {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": "high",
                         "media": "low", "est": 0.009},
    "d35l_g3_low_high": {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "high",
                         "media": "low", "est": 0.009},
    "d35l_v4_low_high": {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "high",
                         "media": "low", "est": 0.010},
    "d35l_g3_low_med": {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "medium",
                        "media": "low", "est": 0.007},
    "d35l_v4_low_min": {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "minimal",
                        "media": "low", "est": 0.004},
    # menos frames (amostra uniforme da janela, primeiro e ultimo sempre dentro)
    "d25f_v1_f16": {"model": "gemini-2.5-flash", "prompt": "v1", "frames": 16, "est": 0.009},
    "d38f_g3_low_low_f16": {"model": "gemini-3.8-flash", "prompt": "g3", "think": "low",
                            "media": "low", "frames": 16, "est": 0.006},
}


def gate_fires() -> dict:
    """event_id -> {braco_do_gate: 1} (uniao de r1 e r2) nos gates de referencia."""
    out = {}
    for arm in GATE_REFS:
        for rep in (1, 2):
            p = RESULTS / f"gate54__{arm}__r{rep}.jsonl"
            if not p.exists():
                continue
            for r in b.latest_ok(p).values():
                if r.get("fire"):
                    out.setdefault(r["event_id"], {})[arm] = 1
    return out


def build_events(subs=None, pick=0):
    fires = gate_fires()
    rows = [r for r in g54.build_set("pass", 0.30) if r["event_id"] in fires]
    for r in rows:
        r["gates"] = sorted(fires[r["event_id"]])
    if subs:
        rows = [r for r in rows if r["sub"] in subs]
    if pick:
        by = {}
        for r in rows:
            by.setdefault(r["sub"], []).append(r)
        rows = [r for s in sorted(by) for r in g54.pick(by[s], pick, salt="detail54|")]
    return rows


def camera_context(win, horario: bool):
    ctx = b.camera_context(win)
    if not horario:
        ctx.pop("horario_local", None)   # producao: so o gate leva horario_local
    return ctx


def out_path(arm: str, rep: int):
    RESULTS.mkdir(parents=True, exist_ok=True)
    return RESULTS / f"detail54__{arm}__r{rep}.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--subs", default="")
    ap.add_argument("--pick", type=int, default=0)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--flex", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    spec = ARMS[a.arm]
    events = build_events(set(a.subs.split(",")) if a.subs else None, a.pick)
    path = out_path(a.arm, a.rep)
    done = b.latest_ok(path) if path.exists() else {}
    todo = [e for e in events if e["event_id"] not in done]
    if a.limit:
        todo = todo[: a.limit]
    for e in todo:
        e["frames"] = [g54.frame_path(n) for n in e["window"].split("|") if n]
    missing = {e["event_id"] for e in todo if len(e["frames"]) < 2 or any(f is None for f in e["frames"])}
    todo = [e for e in todo if e["event_id"] not in missing]
    est = len(todo) * spec["est"] * (0.5 if a.flex else 1.0)
    n_sub = {}
    for e in events:
        n_sub[e["sub"]] = n_sub.get(e["sub"], 0) + 1
    print(f"[detail54] braco={a.arm} modelo={spec['model']} prompt={spec['prompt']} think={spec.get('think')} "
          f"media={spec.get('media')} frames={spec.get('frames')} aviso={spec.get('prior', 'prod')} "
          f"horario={bool(spec.get('horario'))} flex={a.flex}")
    print(f"  eventos={len(events)} {dict(sorted(n_sub.items()))} ja_feitos={len(events) - len(todo) - len(missing)} "
          f"a_rodar={len(todo)} sem_janela={len(missing)} frames_a_rodar={sum(len(e['frames']) for e in todo)} "
          f"estimativa=US$ {est:.4f}")
    if a.dry_run or not todo:
        return
    if a.max_usd <= 0:
        raise SystemExit("informe --max-usd")

    b.use_backend("aistudio")
    budget = Budget(wallet="aistudio")
    budget.run_cap = a.max_usd
    budget.require(est, f"detail54/{a.arm}")
    b._BUDGET = budget
    b._RUN_CTX.update({"campaign": "54", "stage": "detail54", "arm": a.arm, "rep": a.rep,
                       "dataset": "picam-historico", "backend": "aistudio"})
    pv = b.apply_prompt(spec["prompt"])
    prior = g54.prior_contexts() if spec.get("prior", "prod") == "prod" else {}
    if a.flex:
        if not b.flex_ok(spec["model"]):
            raise SystemExit(f"{spec['model']} nao tem Flex na API do AI Studio")
        b._FLEX["on"] = True
        b.cfg.GEMINI_TIMEOUT_SECONDS = FLEX_TIMEOUT_S

    def one(ev):
        win = b.even_subsample(b.build_window(ev["frames"]), spec.get("frames"))
        rec = {"stage": "detail54", "arm": a.arm, "rep": a.rep, "event_id": ev["event_id"],
               "estrato": ev["estrato"], "sub": ev["sub"], "split": ev["split"], "status": ev["status"],
               "detection_id": ev["detection_id"], "gates": ev["gates"], "model": spec["model"],
               "prompt": spec["prompt"], "think": spec.get("think"), "media": spec.get("media"),
               "flex_requested": bool(a.flex), "n_raw": len(ev["frames"]), "n_sent": len(win),
               "bytes_sent": sum(p.stat().st_size for p in win),
               "sent_first": win[0].name, "sent_last": win[-1].name,
               "horario": bool(spec.get("horario")), "require_bbox": bool(b.cfg.GEMINI_REQUIRE_BBOX),
               "backend": "aistudio", "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
        p_type, p_delta, p_src = prior.get(ev["event_id"], (None, None, "desligado"))
        rec.update({"prior_type": p_type, "prior_delta": p_delta, "prior_src": p_src})
        if budget.stop:
            rec["error"] = "budget_stop"
            return rec
        try:
            t0 = time.time()
            d = b.call_backoff(lambda: b.dg.analyze_with_gemini(
                image_paths=win, camera_context=camera_context(win, bool(spec.get("horario"))),
                request_id=str(uuid4()), mosaic_mode=b.cfg.GEMINI_MOSAIC_AGENT2,
                prior_window_context=g54.prior_text(p_type), prompt_version=pv,
                override=b.make_override(spec, "gemini-2.5-flash")))
            dr = d.report
            ti, to, tt = b.usage_tuple(d.usage)
            rec.update({
                "disposal": int(bool(dr.infraction_confirmed)),
                "conf": int(getattr(dr, "confidence_0_100", 0) or 0),
                "waste_type": getattr(dr, "waste_type", "") or "",
                "offender_detected": bool(getattr(dr, "offender_detected", False)),
                "evidence": (getattr(dr, "evidence_summary", "") or "")[:700],
                "tok_in": ti, "tok_out": to, "tok_think": tt,
                "cost_usd": round(cost_usd(spec["model"], ti, to, tt, wallet="aistudio"), 8),
                "latency_ms": int((time.time() - t0) * 1000)})
            rec.update(b.raw_verdict(getattr(d, "raw_json", None), rec["disposal"]))
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        return rec

    n_ok = n_err = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for i, fut in enumerate(as_completed([pool.submit(one, ev) for ev in todo]), 1):
            r = fut.result()
            b.append_jsonl(path, r)
            if r["error"]:
                n_err += 1
                print(f"  [{i}/{len(todo)}] {r['sub']} {r['event_id']} ERR {r['error'][:140]}", flush=True)
            else:
                n_ok += 1
                if i % 25 == 0 or i == len(todo):
                    print(f"  [{i}/{len(todo)}] ok={n_ok} erros={n_err} gasto=US$ {budget.run_spent:.4f} "
                          f"({int(time.time() - t0)} s)", flush=True)
    print(f"  fim: ok={n_ok} erros={n_err} chamadas={json.dumps(b._CALLS)} "
          f"gasto_desta_execucao=US$ {budget.run_spent:.4f} total_carteira=US$ {budget.spent:.4f} "
          f"({int(time.time() - t0)} s)")


if __name__ == "__main__":
    main()
