#!/usr/bin/env python3
"""Camp 51 — Fase A: existe um gate BARATO que preserve recall? (cam_picam001)

Pergunta da campanha (HANDOFF_CHEAP_GATE.md): o Camp 49 concluiu que o detail é
substituível e o gate não. Aqui se testa se algum modelo barato serve de GATE —
preservando os TPs e sem disparar mais que o gate atual.

Fork enxuto de `49-.../scripts/bench_bedrock.py`. Preserva verbatim o que define a
fidelidade (janela de prod, seleção de mids, resumabilidade) e corta o que não
pertence a esta pergunta: **não roda detail nenhum**. Só o estágio 1.

Duas diferenças de método em relação ao Camp 49, deliberadas:

1. **Registra as DUAS regras de decisão por chamada**, sem custo extra:
   - `fire_raw` = o que o próprio prompt decidiu (`new_litter_detected` e conf >= 85);
   - `fire_v1`  = o mesmo report depois do pós-gate determinístico de produção
     (`apply_v1_gate`: scene==DUMPING E 2-de-3 booleanos).
   Sem isso não dá para separar "o modelo errou" de "a pós-regra de prod matou o
   acerto do modelo" — que é exatamente o que aconteceu no FN `evt-20260731_052742`.

2. **Mesmos BYTES para todos os provedores.** As 5 imagens do gate são codificadas
   uma única vez por `_bedrock_client.prepare_images(mode="low")` (640 px, q70) e as
   mesmas são mandadas ao Bedrock e ao Gemini. O controle Gemini do Camp 49 mandava
   imagem original; comparar recall entre provedores com entradas diferentes mediria
   resolução, não modelo.

Uso:
    python scripts/bench_gate51.py --arms gemma-3-4b:min --limit 1 --dry-run
    python scripts/bench_gate51.py --arms gemma-3-4b:min,gemma-3-4b:g3
    python scripts/bench_gate51.py --arms all
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

warnings.filterwarnings("ignore")
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent.parent
CAMP49 = ROOT / "benchmarks" / "campaigns" / "49-picam001-open-weight-tuning-2026-07-31"
CAM = ROOT / "data" / "datasets" / "official" / "cam_picam001"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
CSV_PATH = RESULTS / "gate51_faseA.csv"

# ── janela PROD-exata, ANTES de worker.config (bench_bedrock.py:47-58) ───────
os.environ["GEMINI_CASCADE_MAX_FRAMES"] = "48"
os.environ["GEMINI_MAX_PAYLOAD_BYTES"] = "8000000"
os.environ["GEMINI_GATE_MID_FRAMES"] = "3"
os.environ["GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE"] = "85"
os.environ["GEMINI_AGENT1_THINKING_BUDGET"] = "1024"
os.environ["GEMINI_MAX_OUTPUT_TOKENS"] = "8192"
os.environ["GEMINI_AGENT1_MAX_OUTPUT_TOKENS"] = "8192"
os.environ["GEMINI_TIMEOUT_SECONDS"] = "45"
os.environ.setdefault("GEMINI_MODEL", "gemini-2.5-flash")
os.environ.setdefault("GEMINI_AGENT1_MODEL", "gemini-2.5-flash-lite")
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")

# ── auth do Gemini (só os braços de controle) ───────────────────────────────
# Os dois caminhos de `services/.env.benchmark`, ambos faturando na conta
# **Saira - Testes** (billingAccounts/0149F3), projeto `saira-tests-260520`:
#   C51_GEMINI_AUTH=vertex -> Vertex keyless via ADC (igual à prod)
#   C51_GEMINI_AUTH=key    -> key do AI Studio (fallback documentado)
# Default `key` porque o ADC desta máquina expirou em 31/07 e renová-lo exige colar
# um código no terminal. Para voltar ao Vertex: `gcloud auth application-default
# login` e depois `C51_GEMINI_AUTH=vertex`.
# ⚠️ `GOOGLE_CLOUD_LOCATION=global` é o endpoint que saturou em 16/07 (429 no Agent-2,
# project_gemini_flash_global_429). Aqui e em prod usa-se us-central1.
_AUTH = os.environ.get("C51_GEMINI_AUTH", "key").strip().lower()
_ENVB = ROOT / "services" / ".env.benchmark"
if _AUTH == "key":
    key = os.environ.get("GEMINI_TEST_API_KEY", "").strip()
    if not key and _ENVB.exists():
        for _l in _ENVB.read_text(encoding="utf-8").splitlines():
            _l = _l.strip()
            if _l.startswith("GEMINI_TEST_API_KEY="):
                key = _l.split("=", 1)[1].strip()
                break
    if key:
        os.environ["GEMINI_API_KEY"] = key
        os.environ["GEMINI_TEST_API_KEY"] = key
    os.environ["GEMINI_USE_VERTEX"] = "false"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
else:
    os.environ.setdefault("GEMINI_USE_VERTEX", "true")
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    os.environ.setdefault("GCP_PROJECT", "saira-tests-260520")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "saira-tests-260520")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
sys.path.insert(0, str(CAMP49 / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker.config as cfg                      # noqa: E402
import worker.event_windows as event_windows     # noqa: E402
import worker.detector_gemini as dg              # noqa: E402
import worker._prompts_g3 as p_g3                # noqa: E402
from worker.schemas_gemini import GeminiNewLitterReport   # noqa: E402
import _bedrock_client as bc                     # noqa: E402
import _prompts_v4picam as p_v4                  # noqa: E402
from _prompts_gate51 import GATE_MIN_PROMPT      # noqa: E402

CAMERA_ROW = {"name": "Residencial Via Mangue III - 2", "device_id": "pi-cam-001",
              "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
              "bairro": "Imbiribeira", "rpa": "RPA-1"}
DEVICE_ID = "pi-cam-001"
TRIGGER_THR = 85

# Tarifa Gemini por 1M tokens (in, out). O thinking é cobrado como OUTPUT e TEM que
# ser somado — ver reference_gemini3_bench_cost_keys: sem somar, o custo sai ~2x menor.
GEMINI_PRICE = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-3.1-flash-lite": (0.125, 0.75),
}

GATE_PROMPTS = {
    "min": GATE_MIN_PROMPT,        # Camp 51: pergunta fácil, decisão própria
    "g3":  p_g3.G3_GATE_PROMPT,    # controle: recall-first, o do shadow em prod
    "v1":  dg.NEW_LITTER_SYSTEM_PROMPT,   # o de produção hoje
    "v4":  p_v4.V4_GATE_PROMPT,    # flagrante + catador (reprovou o FN de 31/07)
}

# Candidatos da 1a rodada, + os dois controles.
#
# `gemini-2.5-flash-lite:v1` é o GATE DE PRODUÇÃO HOJE e é o denominador do critério
# de aceite nº 1 ("recall >= 100% do gate atual"). Sem ele medido NESTES 122 eventos
# não existe linha de base — a de 3,5% do handoff é taxa de passagem em tráfego, não
# recall em dataset, e as duas não se comparam.
# `gemini-3.1-flash-lite:g3` é a referência do shadow (86% de recall em tráfego).
DEFAULT_ARMS = [f"{a}:{p}" for a in ("gemma-3-4b", "gemma-3-12b", "ministral-3-14b",
                                     "nemotron-nano-12b", "gemini-3.1-flash-lite")
                for p in ("min", "g3")] + ["gemini-2.5-flash-lite:v1"]


def resolve_arm(name: str) -> dict:
    if ":" not in name:
        raise SystemExit(f"braço '{name}' inválido — use '<alias>:<prompt>' "
                         f"(prompts: {sorted(GATE_PROMPTS)})")
    alias, pv = name.split(":", 1)
    if pv not in GATE_PROMPTS:
        raise SystemExit(f"prompt '{pv}' desconhecido — {sorted(GATE_PROMPTS)}")
    if alias.startswith("gemini-"):
        if alias not in GEMINI_PRICE:
            raise SystemExit(f"sem tarifa para '{alias}' — adicione em GEMINI_PRICE")
        return {"name": name, "provider": "gemini", "alias": alias, "prompt": pv}
    if alias not in bc.MODELS:
        raise SystemExit(f"alias '{alias}' desconhecido — "
                         f"{sorted(a for a in bc.MODELS if a not in bc.ELIMINATED)}")
    if alias in bc.ELIMINATED:
        raise SystemExit(f"alias '{alias}' ELIMINADO pelo probe: {bc.MODELS[alias].note}")
    return {"name": name, "provider": "bedrock", "alias": alias, "prompt": pv}


# ── dataset (verbatim de bench_bedrock.py:174) ───────────────────────────────
def load_events(limit=None, cats=None):
    rows = []
    for cat in ("tp", "fp", "indefinido", "baseline"):
        if cats and cat not in cats:
            continue
        for lab in sorted((CAM / cat).glob("*/label.json")):
            L = json.loads(lab.read_text(encoding="utf-8"))
            frames = sorted((lab.parent / "frames").glob("*.jpg"))
            if len(frames) < 2:
                continue
            rows.append({"event_id": L["event_id"], "category": cat, "frames": frames,
                         "datetime": L.get("datetime", ""),
                         "det_id": L.get("source_detection_id", L["event_id"])})
    rows.sort(key=lambda r: r["event_id"])
    if limit:
        out, seen = [], {}
        for r in rows:
            seen.setdefault(r["category"], 0)
            if seen[r["category"]] < limit:
                out.append(r)
                seen[r["category"]] += 1
        return out
    return rows


# ── janela: verbatim de bench_bedrock.py:210-224 ─────────────────────────────
def gate_mids(win, mid_count=None):
    n = len(win)
    mid_count = max(0, cfg.GEMINI_GATE_MID_FRAMES if mid_count is None else mid_count)
    if n < 3 or mid_count == 0:
        return None
    step = (n - 1) / (mid_count + 1)
    ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
    ks = [k for k in ks if 0 < k < n - 1]
    return [win[k] for k in ks] or None


def build_window(frames):
    win = event_windows.subsample_frames(frames, cfg.GEMINI_CASCADE_MAX_FRAMES)
    return event_windows.fit_frames_to_payload(win, cfg.GEMINI_MAX_PAYLOAD_BYTES)


def camera_context(win):
    hh = ""
    try:
        parts = win[-1].name.split("_")[1].split("-")
        hh = f"{parts[0]}:{parts[1]}"
    except Exception:
        pass
    return {"camera_name": CAMERA_ROW["name"], "device_id": DEVICE_ID,
            "logradouro": CAMERA_ROW["logradouro"], "bairro": CAMERA_ROW["bairro"],
            "rpa": CAMERA_ROW["rpa"], "horario_local": hh}


# ── pós-gate determinístico de prod (detector_gemini.py:1239-1276) ───────────
def apply_v1_gate(report):
    """Opera sobre uma CÓPIA: o runner precisa das duas leituras do mesmo report."""
    r = report.model_copy(deep=True)
    scene = (getattr(r, "scene_type", "") or "").upper().strip()
    if scene != "DUMPING" and r.new_litter_detected:
        r.new_litter_detected = False
        r.confidence_0_100 = 0
    bool_count = sum([bool(getattr(r, "vehicle_stopped", False)),
                      bool(getattr(r, "person_handling_material", False)),
                      bool(getattr(r, "new_ground_material", False))])
    if r.new_litter_detected and bool_count < 2:
        r.new_litter_detected = False
        r.confidence_0_100 = 0
    if not r.new_litter_detected and scene == "DUMPING" and bool_count >= 2:
        r.new_litter_detected = True
        r.confidence_0_100 = max(r.confidence_0_100, 85)
    return r


COLS = ["arm", "provider", "model", "prompt", "event_id", "det_id", "category",
        "n_raw", "n_window", "gate_n_images", "payload_kb",
        "fire_raw", "conf_raw", "fire_v1", "conf_v1", "scene_type",
        "b_vehicle", "b_person", "b_ground", "evidence",
        "json_mode", "json_valid", "tok_in", "tok_out", "tok_think",
        "cost_usd", "latency_ms", "error"]


def gemini_gate(spec, gframes_tmp, guser, cc):
    """Chamada crua ao Gemini com o MESMO system/user/bytes dos braços Bedrock.

    Não usa `analyze_new_litter_with_gemini` de propósito: aquela função aplica o
    pós-gate V1 DENTRO e devolve o report já mutado, o que tornaria `fire_raw`
    inobservável — e `fire_raw` é metade da medição desta campanha.
    """
    t0 = time.time()
    resp = dg._call_model(
        gframes_tmp, GATE_PROMPTS[spec["prompt"]], guser, spec["alias"],
        GeminiNewLitterReport.model_json_schema(),
        cfg.GEMINI_AGENT1_MAX_OUTPUT_TOKENS,
        thinking_budget=cfg.GEMINI_AGENT1_THINKING_BUDGET, seed=42)
    latency = int((time.time() - t0) * 1000)
    report = dg._parse_report_lenient(GeminiNewLitterReport, dg._extract_text(resp))
    report.confidence_0_100 = max(0, min(100, int(report.confidence_0_100)))
    u = getattr(resp, "usage_metadata", None)
    ti = int(getattr(u, "prompt_token_count", 0) or 0)
    to = int(getattr(u, "candidates_token_count", 0) or 0)
    tt = int(getattr(u, "thoughts_token_count", 0) or 0)
    pin, pout = GEMINI_PRICE[spec["alias"]]
    cost = ti / 1e6 * pin + (to + tt) / 1e6 * pout
    return report, ti, to, tt, cost, latency, "native"


def run_event(ev, spec):
    rec = {c: "" for c in COLS}
    rec.update({"arm": spec["name"], "provider": spec["provider"], "model": spec["alias"],
                "prompt": spec["prompt"], "event_id": ev["event_id"], "det_id": ev["det_id"],
                "category": ev["category"], "n_raw": len(ev["frames"]), "cost_usd": 0.0})
    tmps: list[Path] = []
    try:
        win = build_window(ev["frames"])
        rec["n_window"] = len(win)
        mids = gate_mids(win, 3) or []
        gframes = [win[0]] + mids + [win[-1]]
        # Codifica UMA vez; os mesmos bytes vão para Bedrock e Gemini.
        gpay = bc.prepare_images(gframes, mode="low")
        rec["gate_n_images"] = gpay.n_images
        rec["payload_kb"] = round(gpay.raw_bytes / 1024, 1)
        cc = camera_context(win)
        guser = dg._new_litter_user_prompt(
            first_frame_name=win[0].name, last_frame_name=win[-1].name,
            camera_context=cc, prior_window_context=None, mosaic=False,
            mid_frame_names=[p.name for p in mids])

        if spec["provider"] == "bedrock":
            # force_mode="text": vários modelos ACEITAM `toolConfig` e o IGNORAM,
            # devolvendo `confidence` em vez de `confidence_0_100` (armadilha do Camp 48).
            r = bc.converse(spec["alias"], GATE_PROMPTS[spec["prompt"]], guser, gpay.blobs,
                            GeminiNewLitterReport, max_tokens=8192, force_mode="text")
            rec.update({"json_mode": r.json_mode, "json_valid": int(r.json_valid),
                        "tok_in": r.tok_in, "tok_out": r.tok_out, "tok_think": 0,
                        "cost_usd": round(r.cost_usd, 8), "latency_ms": r.latency_ms})
            if not r.json_valid or r.report is None:
                rec["error"] = (r.error or "json inválido")[:250]
                return rec
            report = r.report
        else:
            for blob in gpay.blobs:
                t = tempfile.NamedTemporaryFile(suffix="_c51gate.jpg", delete=False)
                t.write(blob)
                t.close()
                tmps.append(Path(t.name))
            report, ti, to, tt, cost, lat, mode = gemini_gate(spec, tmps, guser, cc)
            rec.update({"json_mode": mode, "json_valid": 1, "tok_in": ti, "tok_out": to,
                        "tok_think": tt, "cost_usd": round(cost, 8), "latency_ms": lat})

        v1 = apply_v1_gate(report)
        rec.update({
            "fire_raw": int(bool(report.new_litter_detected)
                            and int(report.confidence_0_100) >= TRIGGER_THR),
            "conf_raw": int(report.confidence_0_100),
            "fire_v1": int(bool(v1.new_litter_detected)
                           and int(v1.confidence_0_100) >= TRIGGER_THR),
            "conf_v1": int(v1.confidence_0_100),
            "scene_type": (getattr(report, "scene_type", "") or "").upper().strip(),
            "b_vehicle": int(bool(getattr(report, "vehicle_stopped", False))),
            "b_person": int(bool(getattr(report, "person_handling_material", False))),
            "b_ground": int(bool(getattr(report, "new_ground_material", False))),
            "evidence": (getattr(report, "evidence_summary", "") or "")[:300],
        })
    except Exception as exc:  # noqa: BLE001 — o runner nunca pode morrer por 1 evento
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
    finally:
        for p in tmps:
            try:
                p.unlink()
            except OSError:
                pass
    return rec


def load_done(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {(r["arm"], r["event_id"]) for r in csv.DictReader(fh) if not r.get("error")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="all",
                    help="'<alias>:<prompt>' separados por vírgula, ou 'all'")
    ap.add_argument("--cats", default=None, help="tp,fp,indefinido,baseline")
    ap.add_argument("--limit", type=int, default=None, help="N eventos por categoria")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None,
                    help="CSV de saída (default results/gate51_faseA.csv). Serve para "
                         "rodar dois processos em paralelo sem disputar a escrita; "
                         "o agregador lê results/gate51_faseA*.csv.")
    a = ap.parse_args()
    out_path = Path(a.out) if a.out else CSV_PATH
    if not out_path.is_absolute():
        out_path = RESULTS / out_path.name

    arm_names = DEFAULT_ARMS if a.arms == "all" else [s.strip() for s in a.arms.split(",") if s.strip()]
    arms = [resolve_arm(n) for n in arm_names]
    cats = set(a.cats.split(",")) if a.cats else None
    events = load_events(limit=a.limit, cats=cats)

    from collections import Counter
    print(f"eventos: {len(events)} {dict(Counter(e['category'] for e in events))}")
    print(f"braços : {[s['name'] for s in arms]}")
    if a.dry_run:
        ev = events[0]
        win = build_window(ev["frames"])
        mids = gate_mids(win, 3) or []
        pay = bc.prepare_images([win[0]] + mids + [win[-1]], mode="low")
        print(f"dry-run {ev['event_id']}: {len(ev['frames'])} quadros -> janela {len(win)} "
              f"-> gate {pay.n_images} img, {pay.raw_bytes/1024:.0f} KB")
        return

    done = set()
    for p in sorted(RESULTS.glob("gate51_faseA*.csv")):
        done |= load_done(p)
    jobs = [(ev, s) for s in arms for ev in events if (s["name"], ev["event_id"]) not in done]
    print(f"a rodar: {len(jobs)} chamadas (já feitas: {len(done)})")
    new = not out_path.exists()
    with out_path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        if new:
            w.writeheader()
        with ThreadPoolExecutor(max_workers=a.workers) as tp:
            futs = {tp.submit(run_event, ev, s): (ev, s) for ev, s in jobs}
            for i, fut in enumerate(as_completed(futs), 1):
                rec = fut.result()
                w.writerow(rec)
                fh.flush()
                tag = f"ERR {rec['error'][:60]}" if rec["error"] else \
                      f"raw={rec['fire_raw']} v1={rec['fire_v1']} {rec['scene_type']}"
                print(f"[{i}/{len(jobs)}] {rec['arm']:<34} {rec['event_id']:<22} "
                      f"{rec['category']:<10} {tag}", flush=True)
    print(f"\nOK -> {out_path}")


if __name__ == "__main__":
    main()
