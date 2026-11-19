#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — candidatos a gate na amostra do historico da pi-cam-001 (missao 3).

Chama o gate do worker (mesmo codigo de producao, via bench53) com os MESMOS 5 frames que o gate de
producao viu (sample.csv, coluna gate5: primeiro, 3 do meio, ultimo), trocando por braco: modelo,
thinking (budget no 2.5, nivel no Gemini 3), resolucao da imagem e prompt.

Paga pela carteira `aistudio` (trava bench_budget), um braco por execucao. Sempre --dry-run antes.
--flex pede o nivel Flex da API do AI Studio (service_tier=flex, metade do preco); a carteira so
recebe o desconto quando a resposta volta marcada como flex (contagem impressa no fim).

So o conjunto de DESENVOLVIMENTO (nao ha opcao para o de avaliacao). Conjuntos (--set):
  tri     triagem: todos os eventos de deteccoes confirmadas + sorteio fixo (hash) de 40 S2 rejeitados,
          50 S1 e 60 S0 entre os que passam no filtro (nota wl_v2 do q5 r1 >= --thr)
  pass    todos os que passam no filtro + todos os confirmados
  s0fail  sorteio fixo de 200 S0 que NAO passam no filtro (gate sem filtro na frente)

Uso:
  python run_gate54.py --arm g25l_v1_t0 --set tri --flex --dry-run
  python run_gate54.py --arm g25l_v1_t0 --set tri --flex --max-usd 0.10
Saida: ../results/gate54__<braco>__r<rep>.jsonl (um registro por evento; retoma de onde parou).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
C53 = HERE.parents[1] / "53-picam001-migration-post-25flash-2026-11-16" / "scripts"
sys.path.insert(0, str(C53))
sys.path.insert(0, str(HERE))
import bench53 as b          # noqa: E402
from agg_dgate54 import probs  # noqa: E402
from bench_budget import Budget, cost_usd  # noqa: E402

ROOT = Path(r"C:\Saira\data\historico-picam")
FRAME_DIRS = (ROOT / "frames" / "gate5", ROOT / "frames" / "janela")
RESULTS = HERE.parent / "results"
FILTER_FILE = RESULTS / "dgate54__q5_gate5_low__r1.jsonl"
FILTER_Q = "wl_v2"
FLEX_TIMEOUT_S = 600

# budget = thinking_budget do 2.5 (None = nao se aplica); think = thinking_level do Gemini 3.
# est = custo estimado por chamada a preco padrao do AI Studio (US$), para o --dry-run.
ARMS = {
    "g25l_v1_t2048": {"model": "gemini-2.5-flash-lite", "prompt": "v1", "budget": 2048, "est": 0.0012},
    "g25l_v1_t1024": {"model": "gemini-2.5-flash-lite", "prompt": "v1", "budget": 1024, "est": 0.0009},
    "g25l_v1_t512":  {"model": "gemini-2.5-flash-lite", "prompt": "v1", "budget": 512, "est": 0.0007},
    "g25l_v1_t0":    {"model": "gemini-2.5-flash-lite", "prompt": "v1", "budget": 0, "est": 0.0004},
    "g31l_v1_min_low": {"model": "gemini-3.1-flash-lite", "prompt": "v1", "think": "minimal",
                        "media": "low", "est": 0.0012},
    "g31l_v4_min_low": {"model": "gemini-3.1-flash-lite", "prompt": "v4", "think": "minimal",
                        "media": "low", "est": 0.0012},
    "g31l_v1_low_low": {"model": "gemini-3.1-flash-lite", "prompt": "v1", "think": "low",
                        "media": "low", "est": 0.0016},
    "g35l_v1_min_low": {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": "minimal",
                        "media": "low", "est": 0.0016},
    "g35l_v4_min_low": {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "minimal",
                        "media": "low", "est": 0.0016},
    "g31l_v1_min_med": {"model": "gemini-3.1-flash-lite", "prompt": "v1", "think": "minimal",
                        "media": "medium", "est": 0.0016},
    "g38f_v1_low_low": {"model": "gemini-3.8-flash", "prompt": "v1", "think": "low",
                        "media": "low", "est": 0.0030},
    "g38f_v4_low_low": {"model": "gemini-3.8-flash", "prompt": "v4", "think": "low",
                        "media": "low", "est": 0.0030},
    # 19/11 (sessao interativa): prompt g3 do worker (_prompts_g3.G3_GATE_PROMPT, camp 47), escrito
    # para o Gemini 3: aceita descarte a pe, raciocinio antes do JSON, regra de ambiguidade pro-recall.
    # A missao 3 so mediu V1 e V4; o V1 exige "vehicle STOPPED" e o Gemini 3 le isso ao pe da letra.
    "g31l_g3_min_low": {"model": "gemini-3.1-flash-lite", "prompt": "g3", "think": "minimal",
                        "media": "low", "est": 0.0014},
    "g31l_g3_low_low": {"model": "gemini-3.1-flash-lite", "prompt": "g3", "think": "low",
                        "media": "low", "est": 0.0018},
    "g35l_g3_min_low": {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "minimal",
                        "media": "low", "est": 0.0020},
    "g35l_g3_low_low": {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "low",
                        "media": "low", "est": 0.0026},
    # 19/11: v1p = V1 com o descarte a pe permitido (prompts54.py); meio-termo entre o V1 e o g3.
    "g31l_v1p_min_low": {"model": "gemini-3.1-flash-lite", "prompt": "v1p", "think": "minimal",
                         "media": "low", "est": 0.0012},
    "g31l_v1p_low_low": {"model": "gemini-3.1-flash-lite", "prompt": "v1p", "think": "low",
                         "media": "low", "est": 0.0016},
    "g35l_v1p_min_low": {"model": "gemini-3.5-flash-lite", "prompt": "v1p", "think": "minimal",
                         "media": "low", "est": 0.0016},
    "g38f_v1p_low_low": {"model": "gemini-3.8-flash", "prompt": "v1p", "think": "low",
                         "media": "low", "est": 0.0030},
    # 19/11 (missao 4, fidelidade): os mesmos bracos com o "Prior window context" que a producao
    # mandou no gate em 98,7% dos eventos do periodo (ver prior_contexts()).
    "g25l_v1_t2048_ctx": {"model": "gemini-2.5-flash-lite", "prompt": "v1", "budget": 2048,
                          "prior": "prod", "est": 0.0012},
    # temperatura 0.1 = padrao do docker-compose.prod.yml (o replay roda em 0.0, padrao do config.py)
    "g25l_v1_t2048_ctx_t01": {"model": "gemini-2.5-flash-lite", "prompt": "v1", "budget": 2048,
                              "prior": "prod", "temp": 0.1, "est": 0.0012},
    "g31l_v1p_min_low_ctx": {"model": "gemini-3.1-flash-lite", "prompt": "v1p", "think": "minimal",
                             "media": "low", "prior": "prod", "est": 0.0012},
}

# Contexto da janela anterior, como o worker monta (main.py, _process_with_gemini_cascade_window).
PRIOR_TAIL = "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased."
PROD_GATE_TOK_NO_CTX = 2429   # entrada do gate em producao (Vertex) sem o bloco de contexto
# tokens a mais na entrada -> tipo de residuo gravado no estado (contagem do countTokens, 19/11):
# 41 = sem tipo; 46 = Entulho (tambem Poda e Plastico); 48 = Lixo domiciliar. Os de 45, 49 e 51
# nao dao para saber pela contagem: entra um texto do mesmo tamanho (palpite marcado no registro).
PRIOR_BY_DELTA = {41: "", 45: "Mixed", 46: "Entulho", 47: "Entulho", 48: "Lixo domiciliar",
                  49: "Entulho, Poda", 50: "Entulho, Poda", 51: "Entulho, Lixo domiciliar"}


def prior_text(waste_type):
    """None = sem contexto; "" = contexto sem tipo; texto = contexto com o tipo."""
    if waste_type is None:
        return None
    label = f" (type: {waste_type})" if waste_type else ""
    return f"- The previous 2-minute window ALREADY had waste at this location{label}. {PRIOR_TAIL}"


def prior_contexts() -> dict:
    """event_id -> (tipo, delta de tokens, origem). O worker nao grava o contexto que mandou, mas a
    contagem de tokens de entrada da chamada de producao (gemini_call_log) o denuncia: 2.429 sem
    contexto, +41 com contexto sem tipo, +46 com "Entulho" etc. Evento sem par no log leva o caso
    mais comum (contexto com "Entulho", 56% das chamadas do periodo)."""
    tok = {}
    with (ROOT / "raw" / "gemini_call_log_picam.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["agent"] == "gate" and r["success"] == "t" and r["input_tokens"]:
                tok[r["request_id"]] = int(r["input_tokens"])
    out = {}
    with (ROOT / "base" / "base_eventos.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            t = tok.get(r["agent1_request_id"])
            if t is None:
                out[r["event_id"]] = ("Entulho", None, "sem_par")
                continue
            d = t - PROD_GATE_TOK_NO_CTX
            if d < 30:
                out[r["event_id"]] = (None, d, "log")
            elif d in PRIOR_BY_DELTA:
                out[r["event_id"]] = (PRIOR_BY_DELTA[d], d, "log" if d in (41, 46, 48) else "log_palpite")
            else:
                out[r["event_id"]] = ("" if d < 44 else "Entulho", d, "log_palpite")
    return out


def apply_gate_prompt(variant: str) -> str:
    """Prompts proprios da camp 54 (prompts54.GATE_PROMPTS) entram por rebind do prompt V1 do worker,
    com o esquema e a pos-regra do V1; os demais (v1, v4, g3) seguem o bench53."""
    import prompts54
    if variant in prompts54.GATE_PROMPTS:
        b.apply_prompt("v1")
        b.dg.NEW_LITTER_SYSTEM_PROMPT = prompts54.GATE_PROMPTS[variant]
        return "current"
    return b.apply_prompt(variant)


def sub_of(r) -> str:
    if r["estrato"] != "S2":
        return r["estrato"]
    return {"CONFIRMADO": "S2C", "REJEITADO": "S2R"}.get(r["status"], "S2X")


def filter_scores() -> dict:
    out = {}
    for line in FILTER_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("error") and r.get("answers"):
                p = probs(r)
                if FILTER_Q in p:
                    out[r["event_id"]] = p[FILTER_Q]
    return out


def pick(rows, n, salt="gate54|"):
    key = lambda r: hashlib.sha256((salt + r["event_id"]).encode()).hexdigest()  # noqa: E731
    return sorted(rows, key=key)[:n]


def load_dev():
    sc = filter_scores()
    rows = []
    with (ROOT / "amostra" / "sample.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["split"] != "dev":
                continue
            r["sub"] = sub_of(r)
            r["score"] = sc.get(r["event_id"])
            rows.append(r)
    return rows


def build_set(name: str, thr: float, rows=None):
    rows = load_dev() if rows is None else rows
    ok = [r for r in rows if r["score"] is not None]
    passed = [r for r in ok if r["score"] >= thr]
    conf = [r for r in rows if r["sub"] == "S2C"]
    by = lambda s: [r for r in passed if r["sub"] == s]  # noqa: E731
    if name == "tri":
        return conf + pick(by("S2R"), 40) + pick(by("S1"), 50) + pick(by("S0"), 60)
    if name == "pass":
        ids = {r["event_id"] for r in conf}
        return conf + [r for r in passed if r["event_id"] not in ids]
    if name == "s0fail":
        return pick([r for r in ok if r["sub"] == "S0" and r["score"] < thr], 200)
    raise SystemExit(f"conjunto desconhecido: {name}")


def frame_path(name: str):
    for d in FRAME_DIRS:
        p = d / name
        if p.is_file():
            return p
    return None


def out_path(arm: str, rep: int) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    return RESULTS / f"gate54__{arm}__r{rep}.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--set", default="tri", choices=["tri", "pass", "s0fail"])
    ap.add_argument("--thr", type=float, default=0.30)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--flex", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    spec = ARMS[a.arm]
    events = build_set(a.set, a.thr)
    path = out_path(a.arm, a.rep)
    done = b.latest_ok(path) if path.exists() else {}
    todo = [e for e in events if e["event_id"] not in done]
    if a.limit:
        todo = todo[: a.limit]
    for e in todo:
        e["frames"] = [frame_path(n) for n in e["gate5"].split("|")]
    missing = [e["event_id"] for e in todo if len(e["frames"]) < 2 or any(f is None for f in e["frames"])]
    todo = [e for e in todo if e["event_id"] not in set(missing)]
    est = len(todo) * spec["est"] * (0.5 if a.flex else 1.0)
    n_sub = {}
    for e in events:
        n_sub[e["sub"]] = n_sub.get(e["sub"], 0) + 1
    print(f"[gate54] braco={a.arm} modelo={spec['model']} prompt={spec['prompt']} "
          f"budget={spec.get('budget')} think={spec.get('think')} media={spec.get('media')} flex={a.flex}")
    print(f"  conjunto={a.set} (limiar {a.thr}) eventos={len(events)} {dict(sorted(n_sub.items()))} "
          f"ja_feitos={len(events) - len(todo) - len(missing)} a_rodar={len(todo)} sem_frames={len(missing)} "
          f"estimativa=US$ {est:.4f}")
    if a.dry_run or not todo:
        return
    if a.max_usd <= 0:
        raise SystemExit("informe --max-usd")

    b.use_backend("aistudio")
    budget = Budget(wallet="aistudio")
    budget.run_cap = a.max_usd
    budget.require(est, f"gate54/{a.arm}")
    b._BUDGET = budget
    b._RUN_CTX.update({"campaign": "54", "stage": "gate54", "arm": a.arm, "rep": a.rep,
                       "dataset": "picam-historico", "backend": "aistudio"})
    pv = apply_gate_prompt(spec["prompt"])
    prior = prior_contexts() if spec.get("prior") == "prod" else {}
    if spec.get("budget") is not None:
        b.cfg.GEMINI_AGENT1_THINKING_BUDGET = spec["budget"]
    if spec.get("temp") is not None:
        b.cfg.GEMINI_TEMPERATURE = spec["temp"]
    if a.flex:
        if not b.flex_ok(spec["model"]):
            raise SystemExit(f"{spec['model']} nao tem Flex na API do AI Studio")
        b._FLEX["on"] = True
        b.cfg.GEMINI_TIMEOUT_SECONDS = FLEX_TIMEOUT_S
        b.cfg.GEMINI_AGENT1_TIMEOUT_SECONDS = FLEX_TIMEOUT_S

    def one(ev):
        fr = ev["frames"]
        rec = {"stage": "gate54", "arm": a.arm, "rep": a.rep, "event_id": ev["event_id"],
               "estrato": ev["estrato"], "sub": ev["sub"], "split": ev["split"], "status": ev["status"],
               "detection_id": ev["detection_id"], "score": ev["score"], "model": spec["model"],
               "prompt": spec["prompt"], "budget": spec.get("budget"), "temp": b.cfg.GEMINI_TEMPERATURE, "think": spec.get("think"),
               "media": spec.get("media"), "flex_requested": bool(a.flex), "n_sent": len(fr),
               "backend": "aistudio", "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
        p_type, p_delta, p_src = prior.get(ev["event_id"], (None, None, "desligado"))
        rec.update({"prior_type": p_type, "prior_delta": p_delta, "prior_src": p_src})
        if budget.stop:
            rec["error"] = "budget_stop"
            return rec
        try:
            t0 = time.time()
            g = b.call_backoff(lambda: b.dg.analyze_new_litter_with_gemini(
                first_frame=fr[0], last_frame=fr[-1], camera_context=b.camera_context(fr),
                request_id=str(uuid4()), prior_window_context=prior_text(p_type),
                use_mosaic=b.cfg.GEMINI_MOSAIC_AGENT1, mid_frames=fr[1:-1] or None, prompt_version=pv,
                override=b.make_override(spec, "gemini-2.5-flash-lite")))
            gr = g.report
            ti, to, tt = b.usage_tuple(g.usage)
            conf = int(gr.confidence_0_100)
            rec.update({
                "new_litter": bool(gr.new_litter_detected), "conf": conf,
                "fire": int(bool(gr.new_litter_detected) and conf >= b.TRIGGER_THR),
                "scene_type": getattr(gr, "scene_type", ""),
                # os 3 sinais da pos-regra do worker (cena DUMPING + 2 de 3), para explorar outras
                # regras de disparo sem pagar de novo (acrescentado em 19/11)
                "veh_stopped": bool(getattr(gr, "vehicle_stopped", False)),
                "person_handling": bool(getattr(gr, "person_handling_material", False)),
                "new_ground": bool(getattr(gr, "new_ground_material", False)),
                "evidence": (getattr(gr, "evidence_summary", "") or "")[:300],
                # o que o worker grava no estado para a janela seguinte (vira o contexto dela)
                "last_has_litter": bool(getattr(gr, "last_frame_has_litter", False)),
                "waste_type": getattr(gr, "waste_type", None),
                "tok_in": ti, "tok_out": to, "tok_think": tt,
                "cost_usd": round(cost_usd(spec["model"], ti, to, tt, wallet="aistudio"), 8),
                "latency_ms": int((time.time() - t0) * 1000)})
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
                if i % 50 == 0 or i == len(todo):
                    print(f"  [{i}/{len(todo)}] ok={n_ok} erros={n_err} gasto=US$ {budget.run_spent:.4f} "
                          f"({int(time.time() - t0)} s)", flush=True)
    print(f"  fim: ok={n_ok} erros={n_err} chamadas={b._CALLS} gasto_desta_execucao=US$ {budget.run_spent:.4f} "
          f"total_carteira=US$ {budget.spent:.4f} ({int(time.time() - t0)} s)")


if __name__ == "__main__":
    main()
