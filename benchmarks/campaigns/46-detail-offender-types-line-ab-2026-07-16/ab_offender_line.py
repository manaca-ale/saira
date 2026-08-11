#!/usr/bin/env python3
"""Camp 46 — A/B do Agent-2 (detail): linha `offender_types: ...` PRESENTE vs AUSENTE.

HIPÓTESE / SAFETY GATE
  Adicionar UMA linha ao system prompt do detail
    "offender_types: lista com um ou mais valores dentre: pessoa, carro,
     caminhao, moto, carroca, bicicleta, outro."
  NÃO deve mudar `infraction_confirmed`. Só a distribuição de `offender_types`
  pode mudar. Prova para liberar deploy em prod.

BRAÇOS (input IDÊNTICO, mesma janela, mesmos crops):
  B  "with-line"  = código atual (linha presente nos constants de prompt).
  A  "no-line"    = linha removida em runtime (monkeypatch dos constants;
                    NÃO edita os fontes). Strip = a linha + o \n seguinte.

FIDELIDADE A PROD
  * esp32_002 (Mangabeira) → prompt_version="mangabeira_with_pilecrops"
    (_prompts_v3.DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS) + pile_crops hi-res,
    polígono `current` (valor vigente no DB, camp45/polygons.json). É o que prod
    roda para o detail de esp32_002 (GEMINI_DETAIL_PILECROP_ENABLED=true).
  * esp32_001 (Imbiribeira) → prompt_version="current" → detector_gemini.SYSTEM_PROMPT
    (V1 default, = config.GEMINI_PROMPT_VERSION de prod para esp32_001).
  * Chamada REAL: detector_gemini.analyze_with_gemini. Crops via as funções de
    prod main._pile_bbox + main._make_pile_crops.
  * prior_window_context=None nos DOIS braços (idêntico → não afeta o delta A vs B;
    documentado). Model = gemini-2.5-flash (detail de prod), max_out=8192 (prod
    real; 2048 truncava o JSON verboso).

AUTH: Vertex ADC keyless, projeto saira-tests-260520 (conta Saira-Testes). NUNCA prod.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ── env ANTES de importar worker.config (lê os.getenv no import) ─────────────
ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent
_BENCH_ENV = ROOT / "services" / ".env.benchmark"
for _line in _BENCH_ENV.read_text(encoding="utf-8").splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

# Vertex / conta de TESTES (keyless ADC). Espelha camp45.
os.environ["GEMINI_USE_VERTEX"] = "true"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GCP_PROJECT"] = "saira-tests-260520"
os.environ["GOOGLE_CLOUD_PROJECT"] = "saira-tests-260520"
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"        # detail de prod
os.environ["GEMINI_MAX_OUTPUT_TOKENS"] = "8192"        # valor REAL de prod
os.environ["GEMINI_TIMEOUT_SECONDS"] = "45"
os.environ["GEMINI_DETAIL_PILECROP_N_FRAMES"] = "12"
os.environ["GEMINI_DETAIL_PILECROP_UPSCALE"] = "2"
os.environ["DETAIL_HIGHBAR_DEVICES"] = ""              # E_WITH_PILECROPS, NÃO HIGHBAR
os.environ["AI_MODE"] = "gemini"
os.environ["MOCK_MODE"] = "false"
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")  # import-only
os.environ.setdefault("P1_MODEL_PATH", "/dev/null")
os.environ.setdefault("P2_MODEL_PATH", "/dev/null")
# NÃO usar chave/projeto de prod:
os.environ.pop("GEMINI_API_KEY", None)

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.config as cfg                     # noqa: E402
import worker.main as wmain                     # noqa: E402
import worker._prompts_v3 as p3                 # noqa: E402
import worker.detector_gemini as dg             # noqa: E402
from worker.detector_gemini import analyze_with_gemini  # noqa: E402

# ── ABORT se apontar para prod ───────────────────────────────────────────────
assert cfg.GCP_PROJECT == "saira-tests-260520", f"GCP_PROJECT={cfg.GCP_PROJECT} != saira-tests-260520 — ABORT"
assert cfg.GEMINI_USE_VERTEX, "GEMINI_USE_VERTEX deve ser true (billing conta Testes) — ABORT"

# ── a linha sob teste (idêntica em todos os prompts) ─────────────────────────
LINE = ("offender_types: lista com um ou mais valores dentre: "
        "pessoa, carro, caminhao, moto, carroca, bicicleta, outro.")


def strip_line(s: str) -> str:
    """Remove a linha + o \n seguinte (ou o \n anterior, se for a última linha)."""
    return s.replace(LINE + "\n", "").replace("\n" + LINE, "").replace(LINE, "")


# Constants efetivamente usados pelos 2 caminhos de prod que testamos.
_ORIG_SYS = dg.SYSTEM_PROMPT                                   # esp32_001 (current/V1)
_ORIG_MANG = p3.DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS      # esp32_002 (pilecrops)

# Pre-flight: a linha existe em B e some em A, e o delta é exatamente a linha.
for name, orig in (("SYSTEM_PROMPT", _ORIG_SYS),
                   ("DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS", _ORIG_MANG)):
    assert LINE in orig, f"{name}: linha NÃO encontrada (B inválido)"
    stripped = strip_line(orig)
    assert LINE not in stripped, f"{name}: linha ainda presente após strip (A inválido)"
    delta = len(orig) - len(stripped)
    assert delta == len(LINE) + 1, f"{name}: delta={delta} != len(linha)+1={len(LINE)+1}"
    print(f"[preflight] {name}: linha OK, delta={delta} chars")


def set_variant(v: str) -> None:
    """B = com linha (originais); A = sem linha (stripped). Global por fase (thread-safe:
    uma fase inteira roda no mesmo braço)."""
    if v == "B":
        dg.SYSTEM_PROMPT = _ORIG_SYS
        p3.DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS = _ORIG_MANG
    elif v == "A":
        dg.SYSTEM_PROMPT = strip_line(_ORIG_SYS)
        p3.DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS = strip_line(_ORIG_MANG)
    else:
        raise ValueError(v)


# ── polígono pile-zone de prod (esp32_002) ───────────────────────────────────
_POLY_SRC = ROOT / "benchmarks" / "campaigns" / "45-mangabeira-move-geometry-2026-07-15" / "polygons.json"
PILE_POLYGON_CURRENT = json.loads(_POLY_SRC.read_text(encoding="utf-8"))["current"]

# ── dataset ──────────────────────────────────────────────────────────────────
OFFICIAL = ROOT / "data" / "datasets" / "official"
CAM_NAME = {"esp32_002": "Mangabeira", "esp32_001": "Imbiribeira"}
# quantos eventos por (câmera, categoria) — fixo, reprodutível (sort + slice).
SELECT = {
    ("cam_mangabeira", "tp"): 18,
    ("cam_mangabeira", "fp"): 18,
    ("cam_imbiribeira", "tp"): 9,
    ("cam_imbiribeira", "fp"): 9,
}


def parse_ts(name: str) -> datetime:
    try:
        return datetime.strptime(Path(name).stem, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return datetime.min


def sorted_frames(event_dir: Path) -> list[Path]:
    frames = list((event_dir / "frames").glob("*.jpg"))
    frames.sort(key=lambda p: (parse_ts(p.name), p.name))
    if len(frames) > 12:  # amostra uniforme p/ 12 (eventos oficiais já têm 12)
        idxs = [int(round(i * (len(frames) - 1) / 11)) for i in range(12)]
        frames = [frames[i] for i in sorted(set(idxs))]
    return frames


def select_events() -> list[dict]:
    plans: list[dict] = []
    for (cam, cat), n in SELECT.items():
        base = OFFICIAL / cam / cat
        ev_ids = sorted([d.name for d in base.iterdir() if d.is_dir()])[:n]
        for ev in ev_ids:
            ev_dir = base / ev
            label = json.loads((ev_dir / "label.json").read_text(encoding="utf-8"))
            device_id = str(label.get("device_id", "")).strip().lower()
            frames = sorted_frames(ev_dir)
            if len(frames) < 2:
                print(f"[skip] {ev[:8]} {cam}/{cat}: <2 frames")
                continue
            plans.append({
                "event_id": ev, "camera": cam, "category": cat,
                "device_id": device_id, "frames": frames, "label": label,
            })
    return plans


def build_crops(frames: list[Path], out_dir: Path) -> list[Path]:
    """Espelho de main._process_with_gemini (seleção + bbox + upscale de prod)."""
    bbox = wmain._pile_bbox(PILE_POLYGON_CURRENT)
    if not bbox:
        return []
    n_target = min(max(1, cfg.GEMINI_DETAIL_PILECROP_N_FRAMES), len(frames))
    idxs = ([int(round(i * (len(frames) - 1) / (n_target - 1))) for i in range(n_target)]
            if n_target > 1 else [0])
    crop_inputs = [frames[k] for k in idxs]
    return wmain._make_pile_crops(crop_inputs, bbox, cfg.GEMINI_DETAIL_PILECROP_UPSCALE, out_dir)


def camera_context(plan: dict) -> dict:
    lbl = plan["label"]
    return {
        "camera_name": CAM_NAME.get(plan["device_id"], plan["camera"]),
        "device_id": plan["device_id"],
        "logradouro": lbl.get("logradouro", "") or "",
        "bairro": lbl.get("bairro", "") or "",
        "rpa": lbl.get("rpa", "") or "",
    }


_progress = {"done": 0, "total": 0, "cost": 0.0, "lock": threading.Lock()}


def call_with_backoff(fn, tries: int = 5):
    import random
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            transient = any(t in msg for t in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500"))
            if not transient or attempt == tries:
                raise
            sleep = min(90, 8 * 2 ** (attempt - 1)) * (0.7 + 0.6 * random.random())
            print(f"[backoff] {msg[:70]} — retry {attempt}/{tries - 1} em {sleep:.0f}s", flush=True)
            time.sleep(sleep)


def run_one(plan: dict, variant: str) -> dict:
    """Uma janela × um braço. Usa crops pré-gerados (idênticos entre A e B)."""
    is_mang = plan["device_id"] == "esp32_002"
    crops = plan.get("crops") or []
    prompt_version = "mangabeira_with_pilecrops" if (is_mang and crops) else "current"
    rec = {
        "event_id": plan["event_id"], "camera": plan["camera"],
        "ground_truth": plan["category"], "device_id": plan["device_id"],
        "variant": variant, "prompt_version": prompt_version,
        "n_frames": len(plan["frames"]), "n_crops": len(crops),
    }
    try:
        res = call_with_backoff(lambda: analyze_with_gemini(
            image_paths=plan["frames"],
            camera_context=camera_context(plan),
            request_id=f"camp46-{plan['event_id'][:8]}-{variant}",
            mosaic_mode=cfg.GEMINI_MOSAIC_AGENT2,
            prior_window_context=None,
            prompt_version=prompt_version,
            pile_crops=crops or None,
        ))
        rep = res.report
        rec.update({
            "infraction_confirmed": bool(rep.infraction_confirmed),
            "offender_types": list(rep.offender_types or []),
            "offender_detected": bool(getattr(rep, "offender_detected", False)),
            "confidence": int(getattr(rep, "confidence_0_100", 0) or 0),
            "waste_type": getattr(rep, "waste_type", None),
            "input_tokens": int(res.usage.input_tokens),
            "output_tokens": int(res.usage.output_tokens),
            "cost_usd": float(res.usage.estimated_cost_usd or 0.0),
            "latency_ms": int(res.latency_ms),
            "error": None,
        })
    except Exception as exc:  # noqa: BLE001
        rec.update({
            "infraction_confirmed": None, "offender_types": None,
            "offender_detected": None, "confidence": None, "waste_type": None,
            "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0,
            "latency_ms": 0, "error": str(exc)[:300],
        })
    with _progress["lock"]:
        _progress["done"] += 1
        _progress["cost"] += rec["cost_usd"]
        d, t = _progress["done"], _progress["total"]
        st = ("ERR" if rec["error"] else
              ("CONF" if rec["infraction_confirmed"] else "rej"))
        print(f"  [{d}/{t}] {variant} {plan['category']} {plan['event_id'][:8]} "
              f"{plan['device_id']} → {st} ${_progress['cost']:.3f}", flush=True)
    return rec


def run_phase(plans: list[dict], variant: str, workers: int) -> list[dict]:
    set_variant(variant)
    _progress.update({"done": 0, "total": len(plans), "cost": 0.0})
    print(f"\n=== FASE {variant} ({'com linha' if variant == 'B' else 'sem linha'}) "
          f"— {len(plans)} eventos ===", flush=True)
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(run_one, p, variant) for p in plans]
        for fut in as_completed(futs):
            out.append(fut.result())
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    smoke = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--smoke=")), 0)
    workers = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--workers=")), 5)

    print(f"[cfg] model={cfg.GEMINI_MODEL} vertex={cfg.GEMINI_USE_VERTEX} "
          f"project={cfg.GCP_PROJECT} loc={cfg.GCP_LOCATION} "
          f"mosaic2={cfg.GEMINI_MOSAIC_AGENT2!r} max_out={cfg.GEMINI_MAX_OUTPUT_TOKENS} "
          f"crops_n={cfg.GEMINI_DETAIL_PILECROP_N_FRAMES}")

    plans = select_events()
    if smoke:
        plans = plans[:smoke]
    print(f"[data] {len(plans)} eventos selecionados "
          f"({sum(1 for p in plans if p['category']=='tp')} TP / "
          f"{sum(1 for p in plans if p['category']=='fp')} FP)")

    # gera crops UMA vez por evento (idênticos entre A e B); dirs persistem até o fim
    tmp_dirs: list[Path] = []
    for p in plans:
        if p["device_id"] == "esp32_002":
            d = Path(tempfile.mkdtemp(prefix="camp46_crops_"))
            tmp_dirs.append(d)
            p["crops"] = build_crops(p["frames"], d)
        else:
            p["crops"] = []

    if dry:
        for p in plans[:3]:
            print(f"  DRY {p['category']} {p['event_id'][:8]} {p['device_id']} "
                  f"frames={len(p['frames'])} crops={len(p['crops'])} "
                  f"prompt={'mangabeira_with_pilecrops' if p['crops'] else 'current'}")
        print("[dry-run] OK — inputs validados, zero chamadas.")
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        return 0

    try:
        res_b = run_phase(plans, "B", workers)   # com linha (prod atual)
        res_a = run_phase(plans, "A", workers)   # sem linha (baseline)
    finally:
        set_variant("B")  # restaura
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)

    (HERE / "results-B.json").write_text(
        json.dumps(res_b, ensure_ascii=False, indent=2), encoding="utf-8")
    (HERE / "results-A.json").write_text(
        json.dumps(res_a, ensure_ascii=False, indent=2), encoding="utf-8")

    report = build_report(res_a, res_b)
    (HERE / "report.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n→ {HERE / 'results-A.json'}\n→ {HERE / 'results-B.json'}\n→ {HERE / 'report.md'}")
    return 0


def build_report(res_a: list[dict], res_b: list[dict]) -> str:
    a_by = {r["event_id"]: r for r in res_a}
    b_by = {r["event_id"]: r for r in res_b}
    ids = sorted(set(a_by) & set(b_by))

    both_ok = [i for i in ids if a_by[i]["error"] is None and b_by[i]["error"] is None]
    errs = [i for i in ids if a_by[i]["error"] or b_by[i]["error"]]

    agree = [i for i in both_ok if a_by[i]["infraction_confirmed"] == b_by[i]["infraction_confirmed"]]
    disagree = [i for i in both_ok if a_by[i]["infraction_confirmed"] != b_by[i]["infraction_confirmed"]]
    agree_pct = (100.0 * len(agree) / len(both_ok)) if both_ok else 0.0

    def metrics(by, gt):
        pool = [i for i in both_ok if by[i]["ground_truth"] == gt]
        conf = [i for i in pool if by[i]["infraction_confirmed"]]
        return len(conf), len(pool)

    ta_c, ta_n = metrics(a_by, "tp")
    tb_c, tb_n = metrics(b_by, "tp")
    fa_c, fa_n = metrics(a_by, "fp")
    fb_c, fb_n = metrics(b_by, "fp")

    def dist(res):
        c = Counter()
        for r in res:
            if r["error"] is None and r["offender_types"]:
                c.update(r["offender_types"])
        return c
    dist_a, dist_b = dist(res_a), dist(res_b)
    all_types = sorted(set(dist_a) | set(dist_b))

    # nº de eventos em que offender_types diferiu (set-wise)
    ot_changed = [i for i in both_ok
                  if set(a_by[i]["offender_types"] or []) != set(b_by[i]["offender_types"] or [])]

    cost = sum(r["cost_usd"] for r in res_a) + sum(r["cost_usd"] for r in res_b)
    n_calls = sum(1 for r in res_a if r["error"] is None) + sum(1 for r in res_b if r["error"] is None)

    verdict = ("SAFE to deploy (infraction_confirmed unchanged)"
               if not disagree else f"NOT SAFE ({len(disagree)} disagreements)")

    L = []
    L.append("# Camp 46 — Detail `offender_types` line A/B (safety gate)")
    L.append("")
    L.append(f"- Data: {time.strftime('%Y-%m-%d %H:%M')}")
    L.append(f"- Model: {cfg.GEMINI_MODEL} · Vertex `{cfg.GCP_PROJECT}` (conta Saira-Testes)")
    L.append("- Braço B = linha PRESENTE (código atual) · Braço A = linha REMOVIDA (runtime)")
    L.append("- Mangabeira (esp32_002): `mangabeira_with_pilecrops` + pile_crops (polígono `current`).")
    L.append("- Imbiribeira (esp32_001): `current`/V1 `SYSTEM_PROMPT`.")
    L.append("- `prior_window_context=None` nos dois braços (idêntico; não afeta o delta A vs B).")
    L.append("")
    L.append("## 1. infraction_confirmed agreement (SAFETY GATE)")
    L.append("")
    L.append(f"- Eventos com A e B OK: **{len(both_ok)}** (erros: {len(errs)})")
    L.append(f"- A == B: **{len(agree)}/{len(both_ok)} = {agree_pct:.1f}%**")
    L.append(f"- Disagreements: **{len(disagree)}**")
    if disagree:
        L.append("")
        L.append("| event_id | camera | gt | A | B |")
        L.append("|---|---|---|---|---|")
        for i in disagree:
            L.append(f"| {i[:8]} | {a_by[i]['camera']} | {a_by[i]['ground_truth']} | "
                     f"{a_by[i]['infraction_confirmed']} | {b_by[i]['infraction_confirmed']} |")
    L.append("")
    L.append("## 2. TP recall / FP rate por variante (deve ser ~idêntico)")
    L.append("")
    L.append("| variante | TP recall | FP rate (confirm em FP) |")
    L.append("|---|---|---|")
    L.append(f"| A (no-line) | {ta_c}/{ta_n} = {100*ta_c/ta_n if ta_n else 0:.1f}% | "
             f"{fa_c}/{fa_n} = {100*fa_c/fa_n if fa_n else 0:.1f}% |")
    L.append(f"| B (with-line) | {tb_c}/{tb_n} = {100*tb_c/tb_n if tb_n else 0:.1f}% | "
             f"{fb_c}/{fb_n} = {100*fb_c/fb_n if fb_n else 0:.1f}% |")
    L.append("")
    L.append("## 3. offender_types distribution (DEVE mudar — mostra que a linha funciona)")
    L.append("")
    L.append(f"- Eventos com offender_types diferente (set-wise) A vs B: **{len(ot_changed)}/{len(both_ok)}**")
    L.append("")
    L.append("| tipo | A (no-line) | B (with-line) |")
    L.append("|---|---|---|")
    for t in all_types:
        L.append(f"| {t} | {dist_a.get(t, 0)} | {dist_b.get(t, 0)} |")
    L.append(f"| **total menções** | {sum(dist_a.values())} | {sum(dist_b.values())} |")
    L.append("")
    L.append("## 4. Custo e volume")
    L.append("")
    L.append(f"- Chamadas OK: {n_calls} ({len(both_ok)} eventos × 2 braços)")
    L.append(f"- Custo total: **${cost:.4f}** (conta Saira-Testes)")
    L.append("")
    L.append(f"## VEREDITO: {verdict}")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
