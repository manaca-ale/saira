#!/usr/bin/env python3
"""Camp 51 — Fase B: taxa de passagem ABSOLUTA do gate 3.1 em tráfego real.

RODA DENTRO DO CONTAINER DE PRODUÇÃO (os quadros vêm do S3 com as chaves da prod).
Fork enxuto de `/tmp/run_gatekimi.py` (o replay do Camp 50), trocando o detail kimi
sobre a janela cheia pelo GATE sobre 5 quadros.

Por que existe: a Fase A mostrou que nenhum open-weight barato serve de gate, e que o
gate de produção perde 7 de 35 TPs que o `gemini-3.1-flash-lite` recupera. Falta o
número que decide o Plano B de 16/out — **quantos eventos o 3.1 deixaria passar na
rua**, que é o que multiplica o custo do detail.

⚠️ Os 287 eventos do Camp 50 NÃO respondem isso sozinhos: são só aqueles em que o gate
g3 JÁ disparou, então passagem medida ali é `P(passa | g3+)`, condicional. A absoluta é

    P(passa) = P(passa|g3+)·(287/2559) + P(passa|g3−)·(2272/2559)

e por isso este script também sorteia uma amostra dos 2.272 negativos, estratificada
por `gate_scene`, com os 8 que a produção transformou em detecção forçados dentro
(são os furos de recall do próprio g3 — perdê-los na amostragem enviesaria a favor).

FIDELIDADE — replica a configuração do shadow em prod, que NÃO é a da Fase A:
    quadros ORIGINAIS (sem resize) · media_resolution="low" · thinking_level="high"
A Fase A usou 640 px q70 + thinking_budget=1024 porque lá o objetivo era mandar os
MESMOS bytes para Bedrock e Gemini. Aqui o objetivo é outro: ser comparável com os
11,2 % do ledger. Os dois números não se comparam entre si.

Billing: as chamadas usam a key de teste (conta **Saira - Testes**), não o cliente
Gemini de produção — um bench não deve cair na fatura da Prefeitura.

Uso (na EC2):
    docker cp replay_gate51.py saira-yolo-worker-prod:/tmp/
    docker exec -e C51_TEST_KEY=... saira-yolo-worker-prod python /tmp/replay_gate51.py
    docker exec ... python /tmp/replay_gate51.py --neg-sample 500 --prompts g3,min
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import shutil
import sys
import threading
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/app/src")
import boto3                                       # noqa: E402
from google import genai                           # noqa: E402
from worker import config, event_windows           # noqa: E402
from worker import detector_gemini as dg           # noqa: E402
from worker.schemas_gemini import GeminiNewLitterReport   # noqa: E402
import worker._prompts_g3 as p_g3                  # noqa: E402

sys.path.insert(0, "/tmp")
from _prompts_gate51 import GATE_MIN_PROMPT        # noqa: E402

OUT = Path("/app/state/camp51_faseB.jsonl")
TMP = Path("/tmp/camp51")
BUCKET = "saira-images"
DEV = "pi-cam-001"
EV_DIR = Path("/app/uploads/pi-cam-001/events")
MODEL = "gemini-3.1-flash-lite"
TRIGGER_THR = 85
SEED = 51                    # amostragem reprodutível: mesma semente, mesma amostra
PRICE = (0.125, 0.75)        # US$/1M (in, out). Thinking é cobrado como OUTPUT.

PROMPTS = {"g3": p_g3.G3_GATE_PROMPT, "min": GATE_MIN_PROMPT}
CAM_CTX = {"camera_name": "Residencial Via Mangue III - 2", "device_id": DEV,
           "logradouro": "Rua Professor Pedro Augusto Carneiro Leao",
           "bairro": "Imbiribeira", "rpa": "RPA-1"}

lock = threading.Lock()
s3 = boto3.client("s3", region_name=config.S3_REGION,
                  aws_access_key_id=config.AWS_ACCESS_KEY_ID,
                  aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY)
_key = os.environ.get("C51_TEST_KEY", "").strip()
if not _key:
    raise SystemExit("falta C51_TEST_KEY (key do AI Studio, conta Saira - Testes). "
                     "Sem ela o bench cairia na fatura de produção.")
gclient = genai.Client(api_key=_key)


def gate_mids(win):
    """Verbatim de main.py:_shadow_gate_mids — 1º + N mids + último."""
    n = len(win)
    mid_count = max(0, config.GEMINI_GATE_MID_FRAMES)
    if n < 3 or mid_count == 0:
        return None
    step = (n - 1) / (mid_count + 1)
    ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
    ks = [k for k in ks if 0 < k < n - 1]
    return [win[k] for k in ks] or None


def apply_v1_gate(report):
    r = report.model_copy(deep=True)
    scene = (getattr(r, "scene_type", "") or "").upper().strip()
    if scene != "DUMPING" and r.new_litter_detected:
        r.new_litter_detected, r.confidence_0_100 = False, 0
    bc_ = sum([bool(getattr(r, "vehicle_stopped", False)),
               bool(getattr(r, "person_handling_material", False)),
               bool(getattr(r, "new_ground_material", False))])
    if r.new_litter_detected and bc_ < 2:
        r.new_litter_detected, r.confidence_0_100 = False, 0
    if not r.new_litter_detected and scene == "DUMPING" and bc_ >= 2:
        r.new_litter_detected = True
        r.confidence_0_100 = max(r.confidence_0_100, 85)
    return r


def select_targets(neg_sample: int) -> list[dict]:
    rows = [json.loads(l) for f in glob.glob("/app/state/shadow_model_audit/*/*.jsonl")
            for l in open(f, encoding="utf-8") if l.strip()]
    g3 = [r for r in rows if r.get("prompt") == "g3"]
    pos = [r for r in g3 if r.get("gate_triggered")]
    neg = [r for r in g3 if not r.get("gate_triggered")]
    print(f"ledger g3: {len(g3)} ({len(pos)} positivos, {len(neg)} negativos)")

    # Os negativos em que a PRODUÇÃO criou detecção são os furos de recall do g3.
    # São 8 e entram todos: numa amostra de 500 sobre 2.272 a chance de perder algum
    # é alta, e perdê-los mediria o g3 melhor do que ele é.
    forced = [r for r in neg if r.get("prod_created_detection")]
    rest = [r for r in neg if not r.get("prod_created_detection")]
    # Estratificação por cena: sem ela, TRAFFIC (65 % dos negativos) domina a amostra e
    # EMPTY/PARKED ficam sub-representados justamente onde o disparo indevido importa.
    by_scene = defaultdict(list)
    for r in rest:
        by_scene[r.get("gate_scene") or "?"].append(r)
    rng = random.Random(SEED)
    quota = max(0, neg_sample - len(forced))
    sample = []
    for scene, items in sorted(by_scene.items()):
        k = round(quota * len(items) / len(rest))
        rng.shuffle(items)
        sample += items[:k]
    print(f"amostra de negativos: {len(sample)} + {len(forced)} forçados "
          f"(prod criou detecção) — estratos "
          f"{ {s: sum(1 for r in sample if r.get('gate_scene') == s) for s in by_scene} }")

    out = []
    for r in pos:
        out.append({**r, "_strato": "g3_pos"})
    for r in forced + sample:
        out.append({**r, "_strato": "g3_neg"})
    return out


def run_one(r: dict, pool: Path, prompt_key: str) -> dict:
    ev = r["event_ref"]
    rec = {"event_ref": ev, "ts": r["ts"], "prompt": prompt_key, "model": MODEL,
           "strato": r["_strato"], "ledger_triggered": bool(r.get("gate_triggered")),
           "ledger_conf": r.get("gate_confidence"), "ledger_scene": r.get("gate_scene"),
           "prod_created": bool(r.get("prod_created_detection")),
           "prod_detection_id": r.get("prod_detection_id"),
           "ledger_window": r.get("window_size"), "cost_usd": 0.0, "error": ""}
    try:
        mani = json.loads((EV_DIR / f"{ev}.json").read_text(encoding="utf-8"))
        names = [Path(f).name for f in mani.get("frames", [])]
        paths = [pool / n for n in names if (pool / n).exists()]
        rec["frames_no_manifest"] = len(names)
        rec["frames_resolvidos"] = len(paths)
        if len(paths) < 2:
            rec["error"] = "frames nao resolvidos"
            return rec
        win = event_windows.subsample_frames(paths, config.GEMINI_CASCADE_MAX_FRAMES)
        win = event_windows.fit_frames_to_payload(win, config.GEMINI_MAX_PAYLOAD_BYTES)
        mids = gate_mids(win) or []
        gframes = [win[0]] + mids + [win[-1]]
        rec["n_window"] = len(win)
        rec["gate_n_images"] = len(gframes)
        hh = ""
        try:
            p = win[-1].name.split("_")[1].split("-")
            hh = f"{p[0]}:{p[1]}"
        except Exception:
            pass
        user = dg._new_litter_user_prompt(
            first_frame_name=win[0].name, last_frame_name=win[-1].name,
            camera_context={**CAM_CTX, "horario_local": hh},
            prior_window_context=None, mosaic=False,
            mid_frame_names=[p.name for p in mids])
        t0 = time.time()
        resp = dg._call_model(
            gframes, PROMPTS[prompt_key], user, MODEL,
            GeminiNewLitterReport.model_json_schema(),
            config.GEMINI_AGENT1_MAX_OUTPUT_TOKENS,
            thinking_budget=None, seed=42,
            thinking_level="high", media_resolution="low", client=gclient)
        rec["latency_ms"] = int((time.time() - t0) * 1000)
        rep = dg._parse_report_lenient(GeminiNewLitterReport, dg._extract_text(resp))
        rep.confidence_0_100 = max(0, min(100, int(rep.confidence_0_100)))
        v1 = apply_v1_gate(rep)
        u = getattr(resp, "usage_metadata", None)
        ti = int(getattr(u, "prompt_token_count", 0) or 0)
        to = int(getattr(u, "candidates_token_count", 0) or 0)
        tt = int(getattr(u, "thoughts_token_count", 0) or 0)
        rec.update({
            "fire_raw": int(bool(rep.new_litter_detected)
                            and int(rep.confidence_0_100) >= TRIGGER_THR),
            "conf_raw": int(rep.confidence_0_100),
            "fire_v1": int(bool(v1.new_litter_detected)
                           and int(v1.confidence_0_100) >= TRIGGER_THR),
            "scene_type": (getattr(rep, "scene_type", "") or "").upper().strip(),
            "b_vehicle": int(bool(getattr(rep, "vehicle_stopped", False))),
            "b_person": int(bool(getattr(rep, "person_handling_material", False))),
            "b_ground": int(bool(getattr(rep, "new_ground_material", False))),
            "evidence": (getattr(rep, "evidence_summary", "") or "")[:300],
            "tok_in": ti, "tok_out": to, "tok_think": tt,
            "cost_usd": round(ti / 1e6 * PRICE[0] + (to + tt) / 1e6 * PRICE[1], 8),
        })
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return rec


def fetch_day(day: str, evs: list[dict], pool: Path) -> None:
    """Um zip por dia no S3 + fallback por quadro solto (igual ao replay do Camp 50)."""
    wanted = set()
    for r in evs:
        try:
            m = json.loads((EV_DIR / f"{r['event_ref']}.json").read_text(encoding="utf-8"))
            wanted.update(Path(f).name for f in m.get("frames", []))
        except Exception:
            pass
    zp = TMP / f"{day}.zip"
    try:
        s3.download_file(BUCKET, f"descartadas/{DEV}/{day}/{DEV}_{day}.zip", str(zp))
        with zipfile.ZipFile(zp) as z:
            idx = {Path(n).name: n for n in z.namelist()}
            for n in wanted & set(idx):
                with z.open(idx[n]) as src, open(pool / n, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    except Exception as e:
        print(f"  {day} zip: {type(e).__name__} {str(e)[:90]}", flush=True)
    finally:
        zp.unlink(missing_ok=True)
    y, mo, dd = day.split("-")
    for n in [n for n in wanted if not (pool / n).exists()]:
        for pref in (f"ocorrencias/{DEV}/{y}/{mo}/{dd}/{n}", f"ocorrencias/{DEV}/{day}/{n}"):
            try:
                s3.download_file(BUCKET, pref, str(pool / n))
                break
            except Exception:
                continue
    got = sum(1 for n in wanted if (pool / n).exists())
    print(f"{day}: {len(evs)} eventos, {got}/{len(wanted)} quadros", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--neg-sample", type=int, default=500)
    ap.add_argument("--prompts", default="g3,min")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    prompts = [p.strip() for p in a.prompts.split(",") if p.strip() in PROMPTS]

    targets = select_targets(a.neg_sample)
    done = set()
    if OUT.exists():
        for l in OUT.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                if not d.get("error"):
                    done.add((d["event_ref"], d["prompt"]))
    jobs = [(r, p) for r in targets for p in prompts if (r["event_ref"], p) not in done]
    print(f"alvos {len(targets)} x {len(prompts)} prompts = {len(jobs)} chamadas "
          f"(já feitas: {len(done)})")
    if a.dry_run:
        return

    by_day = defaultdict(list)
    for r in targets:
        by_day[r["ts"][:10]].append(r)
    TMP.mkdir(parents=True, exist_ok=True)
    for day in sorted(by_day):
        evs = by_day[day]
        day_jobs = [(r, p) for (r, p) in jobs if r["ts"][:10] == day]
        if not day_jobs:
            continue
        pool = TMP / day
        shutil.rmtree(pool, ignore_errors=True)
        pool.mkdir(parents=True, exist_ok=True)
        fetch_day(day, evs, pool)
        with ThreadPoolExecutor(max_workers=a.workers) as tp:
            for rec in tp.map(lambda t: run_one(t[0], pool, t[1]), day_jobs):
                with lock, OUT.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        shutil.rmtree(pool, ignore_errors=True)
        print(f"  {day} concluído ({len(day_jobs)} chamadas)", flush=True)
    print("FIM ->", OUT, flush=True)


if __name__ == "__main__":
    main()
