#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 54 — triagem dos modelos Nova (AWS Bedrock) como GATE, nos mesmos conjuntos do run_gate54.py.

Por que existe: sem o gemini-2.5-flash-lite nao ha gate substituto medido (missao 3). Os modelos de peso
aberto do Bedrock ja foram reprovados como gate em julho (campanhas 48, 49 e 51); so a familia Nova da
Amazon (Lite, 2 Lite, Pro) nunca tinha sido testada. Aprovado pelo Alexandre em 19/11/2026, teto US$ 3,00
(carteira `bedrock` do budget.json; conta AWS dele, coberta por creditos).

Mesma medida dos bracos Gemini: os 5 frames que o gate de producao viu, o prompt do worker (system e user),
o esquema GeminiNewLitterReport e a pos-regra do worker (cena DUMPING + 2 de 3 sinais; dispara com
confianca >= 85). O registro sai no formato do run_gate54.py (`new_litter` e `conf` DEPOIS da pos-regra),
entao `agg_gate54.py` e `explore_gate54_rules.py` leem os dois sem mudanca; a resposta crua do modelo
fica em `new_litter_raw` e `conf_raw`.

Transporte: cliente Converse da campanha 48 (`_bedrock_client.py`), com JSON em texto (`force_mode="text"`),
como na campanha 51. Imagens: `low` = 640 px, qualidade 70 (o analogo do media_resolution=low);
`orig` = os bytes do disco (1280x720).

Credencial: chave do Bedrock em C:\\Users\\User\\.saira-bench\\bedrock_key.txt (so invoca os candidatos a
gate; expira em 26/11/2026). E lida para a variavel de ambiente DESTE processo e nunca e impressa.

So o conjunto de DESENVOLVIMENTO. Sempre --dry-run antes.

Uso:
  python run_gate54_bedrock.py --arm nvl_v1_low --set tri --dry-run
  python run_gate54_bedrock.py --arm nvl_v1_low --set tri --limit 2 --max-usd 0.01     # sonda de tokens
  python run_gate54_bedrock.py --arm nvl_v1_low --set tri --max-usd 0.15
Saida: ../results/gate54__<braco>__r<rep>.jsonl (um registro por evento; retoma de onde parou).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
C48 = HERE.parents[1] / "48-bedrock-oss-vlm-picam001-2026-07-30" / "scripts"
sys.path.insert(0, str(HERE))
import run_gate54 as g                    # noqa: E402  (traz o bench53, o worker no sys.path e os conjuntos)
sys.path.insert(0, str(C48))
import _bedrock_client as bc              # noqa: E402
import prompts54                          # noqa: E402
import worker._prompts_g3 as p_g3         # noqa: E402
from worker.schemas_gemini import GeminiNewLitterReport  # noqa: E402
from bench_budget import PRICES, Budget, cost_usd  # noqa: E402

b = g.b
dg = b.dg

KEY_FILE = Path(r"C:\Users\User\.saira-bench\bedrock_key.txt")
REGION = "us-east-1"

# alias -> (id do modelo ou do perfil de inferencia, codigo curto para o nome do braco).
# Precos em bench_budget.PRICES (lista publica da AWS, us-east-1, lida em 19/11/2026).
NOVA = {
    "nova-lite": ("amazon.nova-lite-v1:0", "nvl"),
    "nova-2-lite": ("us.amazon.nova-2-lite-v1:0", "nv2l"),   # so por perfil de inferencia
    "nova-pro": ("amazon.nova-pro-v1:0", "nvp"),
}
for _alias, (_mid, _code) in NOVA.items():
    bc.MODELS[_alias] = bc.ModelSpec(_alias, _mid, None, PRICES[_alias], False,
                                     "Nova (Amazon): triagem de 19/11/2026")

PROMPTS = {
    "v1": prompts54._V1,                      # o de producao
    "g3": p_g3.G3_GATE_PROMPT,                # pro-recall, aceita descarte a pe (camp 47)
    "v1p": prompts54.GATE_PROMPTS["v1p"],     # V1 com o descarte a pe permitido (19/11)
}
# Estimativa por chamada (US$) para o --dry-run, medida na sonda de 19/11 (ver o handoff, secao 12.4).
# Sonda de 19/11, 08:47, 5 imagens `low`: Nova Lite e Pro 4.724 tokens de entrada, Nova 2 Lite 2.179; saida ~200.
# Os valores `orig` sao chute (nao medidos).
EST = {("nova-lite", "low"): 0.00035, ("nova-lite", "orig"): 0.0007,
       ("nova-2-lite", "low"): 0.0013, ("nova-2-lite", "orig"): 0.0030,
       ("nova-pro", "low"): 0.0045, ("nova-pro", "orig"): 0.0090}
ARMS = {f"{code}_{pv}_{img}": {"alias": alias, "prompt": pv, "img": img, "est": EST[(alias, img)]}
        for alias, (_m, code) in NOVA.items() for pv in PROMPTS for img in ("low", "orig")}


def make_client():
    """Cliente bedrock-runtime autenticado pela chave do Bedrock (bearer). Nunca imprime a chave."""
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = KEY_FILE.read_text(encoding="utf-8").strip()
    for k in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        os.environ.pop(k, None)
    import boto3
    from botocore.config import Config
    return boto3.Session(region_name=REGION).client(
        "bedrock-runtime",
        config=Config(retries={"max_attempts": 3, "mode": "adaptive"}, read_timeout=120, connect_timeout=20))


def apply_v1_gate(report):
    """Pos-regra do worker (detector_gemini.analyze_new_litter_with_gemini, ramo V1), sobre uma copia."""
    r = report.model_copy(deep=True)
    scene = (getattr(r, "scene_type", "") or "").upper().strip()
    if scene != "DUMPING" and r.new_litter_detected:
        r.new_litter_detected = False
        r.confidence_0_100 = 0
    n = sum([bool(getattr(r, "vehicle_stopped", False)), bool(getattr(r, "person_handling_material", False)),
             bool(getattr(r, "new_ground_material", False))])
    if r.new_litter_detected and n < 2:
        r.new_litter_detected = False
        r.confidence_0_100 = 0
    if not r.new_litter_detected and scene == "DUMPING" and n >= 2:
        r.new_litter_detected = True
        r.confidence_0_100 = max(r.confidence_0_100, 85)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=sorted(ARMS))
    ap.add_argument("--set", default="tri", choices=["tri", "pass", "s0fail"])
    ap.add_argument("--subs", default="", help="so estes estratos, separados por virgula (ex.: S2C,S0)")
    ap.add_argument("--thr", type=float, default=0.30)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-usd", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    spec = ARMS[a.arm]
    alias, model_id = spec["alias"], NOVA[spec["alias"]][0]
    events = g.build_set(a.set, a.thr)
    if a.subs:
        keep = {s.strip() for s in a.subs.split(",") if s.strip()}
        events = [e for e in events if e["sub"] in keep]
    path = g.out_path(a.arm, a.rep)
    done = b.latest_ok(path) if path.exists() else {}
    todo = [e for e in events if e["event_id"] not in done]
    if a.limit:
        todo = todo[: a.limit]
    for e in todo:
        e["frames"] = [g.frame_path(n) for n in e["gate5"].split("|")]
    missing = [e["event_id"] for e in todo if len(e["frames"]) < 2 or any(f is None for f in e["frames"])]
    todo = [e for e in todo if e["event_id"] not in set(missing)]
    est = len(todo) * spec["est"]
    n_sub = {}
    for e in events:
        n_sub[e["sub"]] = n_sub.get(e["sub"], 0) + 1
    print(f"[gate54/bedrock] braco={a.arm} modelo={alias} ({model_id}) prompt={spec['prompt']} imagens={spec['img']}")
    print(f"  conjunto={a.set} (limiar {a.thr}) eventos={len(events)} {dict(sorted(n_sub.items()))} "
          f"ja_feitos={len(events) - len(todo) - len(missing)} a_rodar={len(todo)} sem_frames={len(missing)} "
          f"estimativa=US$ {est:.4f}")
    if a.dry_run or not todo:
        return
    if a.max_usd <= 0:
        raise SystemExit("informe --max-usd")

    budget = Budget(wallet="bedrock")
    budget.run_cap = a.max_usd
    budget.require(est, f"gate54/{a.arm}")
    ctx = {"campaign": "54", "stage": "gate54", "arm": a.arm, "rep": a.rep,
           "dataset": "picam-historico", "backend": "bedrock"}
    bc._client = make_client()
    system = PROMPTS[spec["prompt"]]

    def one(ev):
        fr = ev["frames"]
        rec = {"stage": "gate54", "arm": a.arm, "rep": a.rep, "event_id": ev["event_id"],
               "estrato": ev["estrato"], "sub": ev["sub"], "split": ev["split"], "status": ev["status"],
               "detection_id": ev["detection_id"], "score": ev["score"], "model": alias, "model_id": model_id,
               "prompt": spec["prompt"], "budget": None, "think": None, "media": spec["img"],
               "flex_requested": False, "n_sent": len(fr), "backend": "bedrock",
               "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
        if budget.stop:
            rec["error"] = "budget_stop"
            return rec
        try:
            pay = bc.prepare_images(fr, mode=spec["img"])
            user = dg._new_litter_user_prompt(
                first_frame_name=fr[0].name, last_frame_name=fr[-1].name, camera_context=b.camera_context(fr),
                prior_window_context=None, mosaic=False, mid_frame_names=[p.name for p in fr[1:-1]])
            r = bc.converse(alias, system, user, pay.blobs, GeminiNewLitterReport,
                            max_tokens=2000, force_mode="text")
            if r.tok_in:
                budget.charge(alias, r.tok_in, r.tok_out, 0, ctx=ctx)
            rec.update({"tok_in": r.tok_in, "tok_out": r.tok_out, "tok_think": 0,
                        "cost_usd": round(cost_usd(alias, r.tok_in, r.tok_out), 8),
                        "latency_ms": r.latency_ms, "payload_kb": round(pay.raw_bytes / 1024, 1),
                        "n_dropped": pay.n_dropped, "json_mode": r.json_mode})
            if not r.json_valid or r.report is None:
                rec["error"] = (r.error or "json invalido")[:250]
                rec["raw"] = (r.raw_text or "")[:300]
                return rec
            rep = r.report
            rep.confidence_0_100 = max(0, min(100, int(rep.confidence_0_100)))
            v1 = apply_v1_gate(rep)
            conf = int(v1.confidence_0_100)
            rec.update({
                "new_litter": bool(v1.new_litter_detected), "conf": conf,
                "fire": int(bool(v1.new_litter_detected) and conf >= b.TRIGGER_THR),
                "new_litter_raw": bool(rep.new_litter_detected), "conf_raw": int(rep.confidence_0_100),
                "scene_type": (getattr(rep, "scene_type", "") or "").upper().strip(),
                "veh_stopped": bool(getattr(rep, "vehicle_stopped", False)),
                "person_handling": bool(getattr(rep, "person_handling_material", False)),
                "new_ground": bool(getattr(rep, "new_ground_material", False)),
                "evidence": (getattr(rep, "evidence_summary", "") or "")[:300]})
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
                print(f"  [{i}/{len(todo)}] {r['sub']} {r['event_id']} ERR {r['error'][:160]}", flush=True)
            else:
                n_ok += 1
                if i <= 2 or i % 50 == 0 or i == len(todo):
                    print(f"  [{i}/{len(todo)}] ok={n_ok} erros={n_err} tok_in={r['tok_in']} tok_out={r['tok_out']} "
                          f"US$/chamada={r['cost_usd']:.6f} lat={r['latency_ms']} ms | gasto=US$ {budget.run_spent:.4f} "
                          f"({int(time.time() - t0)} s)", flush=True)
    print(f"  fim: ok={n_ok} erros={n_err} gasto_desta_execucao=US$ {budget.run_spent:.4f} "
          f"total_carteira_bedrock=US$ {budget.spent:.4f} ({int(time.time() - t0)} s)")


if __name__ == "__main__":
    main()
