#!/usr/bin/env python3
"""Camp 45 — A/B OFFLINE do Agent-2 (detail) esp32_002 pós-mudança de posição.

Braços (todos sobre as MESMAS 153 janelas rotuladas do audit — 14 CONF + 139 REJ):

  A  prod-hoje    detail SYSTEM_PROMPT_V3 genérico, SEM pilecrops.
  B  proposto     pilecrops LIGADOS (polígono `proposed`) + DETAIL_PROMPT_MANGABEIRA_HIGHBAR.
  C  controle     pilecrops (polígono `proposed`) + DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS
                  (prompt anterior ao HIGHBAR — isola "crops" de "prompt HIGHBAR").
  D  controle-geo pilecrops + HIGHBAR com o polígono `current` (stale) — isola o polígono.

FIDELIDADE AO INPUT DE PROD (regra de ouro desta base — camps 20/21 foram
invalidadas por sub-amostragem):

  * A janela é reconstruída a partir do audit de prod: TODOS os frames com
    first <= nome <= last no índice GLOBAL por nome (janelas cruzam meia-noite;
    day10/ contém 38 frames capturados em 09/07). O harness ABORTA a janela se
    len(window) != window_size do audit — isto é, se o input não bater
    exatamente com o que prod mandou. (Nas 153 rotuladas, window_size == n_found
    em 153/153, então a reconstrução é exata e não há trimming de payload.)
  * `event_windows.fit_frames_to_payload` é aplicado como em prod
    (main.py:1347) — mesmo ponto de passagem, mesmo teto de bytes.
  * A chamada é a REAL: `detector_gemini.analyze_with_gemini`. Crops via
    `main._pile_bbox` + `main._make_pile_crops` (as funções de prod).
  * A seleção dos 12 frames de crop e o camera_context replicam verbatim
    `main._process_with_gemini` (main.py:808-884). Ver `build_pile_crops()`.
  * Sem mosaico inventado: mosaic_mode = config.GEMINI_MOSAIC_AGENT2 (prod: "off").

⚠️ SUBSET: as 153 janelas rotuladas são, POR CONSTRUÇÃO, janelas em que o
Agent-2 de prod disse disposal=TRUE (só assim vira detecção e recebe status do
operador). Logo a "taxa de rejeição" medida aqui = % das confirmações de prod
que o braço mataria — NÃO é comparável direto com os 52,8%/73,9% do audit, que
são sobre TODAS as chamadas do Agent-2. Para a taxa fleet-wide use
--include-trig (roda também as 189 janelas TRIG_NOLABEL = gate subiu e o
Agent-2 rejeitou). Ver `summary["rejection_rate"]`.

Uso:
  python scripts/detail_ab.py --dry-run              # valida input, zero custo
  python scripts/detail_ab.py --arms A,B,C --workers 5
  python scripts/detail_ab.py --arms D               # incremental (resume por CSV)
  python scripts/detail_ab.py --aggregate-only       # só recomputa métricas
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

warnings.filterwarnings("ignore")
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent.parent
DATA = ROOT / "tmp" / "mangabeira_move"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

CSV_PATH = RESULTS / "detail_ab.csv"
SUMMARY_PATH = RESULTS / "detail_ab_summary.json"
SECTION_PATH = RESULTS / "detail_ab_report_section.md"
PRIOR_PATH = RESULTS / "detail_ab_prior_state.json"

# ── env de PROD (valores confirmados p/ esp32_002) + auth de TESTE ───────────
# Precisa vir ANTES de importar worker.config (lê os.getenv no import).
_BENCH_ENV = ROOT / "services" / ".env.benchmark"
for _line in _BENCH_ENV.read_text(encoding="utf-8").splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

os.environ["GEMINI_USE_VERTEX"] = "true"          # billing = conta Saira - Testes
os.environ["GCP_PROJECT"] = "saira-tests-260520"
os.environ["GOOGLE_CLOUD_PROJECT"] = "saira-tests-260520"
os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"   # detail de prod
os.environ["GEMINI_MAX_OUTPUT_TOKENS"] = "8192"   # valor REAL de prod (docker inspect 16/07);
                                                  # 2048 truncava o JSON do V3 verboso (braço A)
os.environ["GEMINI_AGENT1_MAX_OUTPUT_TOKENS"] = "4096"   # gate (prior probe)
os.environ["GEMINI_TIMEOUT_SECONDS"] = "45"
os.environ["GEMINI_DETAIL_PILECROP_N_FRAMES"] = "12"
os.environ["GEMINI_DETAIL_PILECROP_UPSCALE"] = "2"
os.environ["GEMINI_AGENT1_MODEL"] = "gemini-2.5-flash-lite"   # só p/ --prior-mode probe
os.environ["GEMINI_AGENT1_THINKING_BUDGET"] = "1024"
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")  # import-only

sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.config as cfg                     # noqa: E402
import worker.event_windows as event_windows    # noqa: E402
import worker.main as wmain                     # noqa: E402
import worker._prompts_v3 as p3                 # noqa: E402
from worker.detector_gemini import (            # noqa: E402
    analyze_new_litter_with_gemini,
    analyze_with_gemini,
)

# esp32_002 no DB (snapshot camp 36, cameras.json — id 11). O polígono NÃO vem
# daqui: cada braço injeta o seu (polygons.json).
CAMERA_ROW = {
    "id": 11,
    "device_id": "esp32_002",
    "name": "Mangabeira",
    "logradouro": "Av. Prof. José dos Anjos, 3254",
    "bairro": "Mangabeira",
    "rpa": "RPA 5",
}
DEVICE_ID = "esp32_002"

POLYGONS = json.loads((HERE / "polygons.json").read_text(encoding="utf-8"))

# arm → (polygon_key | None, highbar?, rótulo do prompt esperado)
ARMS: dict[str, dict] = {
    "A": {"polygon": None, "highbar": False, "prompt": "SYSTEM_PROMPT_V3",
          "desc": "prod hoje: V3 genérico, sem pilecrops"},
    "B": {"polygon": "proposed", "highbar": True, "prompt": "DETAIL_PROMPT_MANGABEIRA_HIGHBAR",
          "desc": "proposto: pilecrops (proposed) + HIGHBAR"},
    "C": {"polygon": "proposed", "highbar": False,
          "prompt": "DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS",
          "desc": "controle: pilecrops (proposed) + prompt E"},
    "D": {"polygon": "current", "highbar": True, "prompt": "DETAIL_PROMPT_MANGABEIRA_HIGHBAR",
          "desc": "controle-geo: pilecrops (current/stale) + HIGHBAR"},
}

CSV_COLS = [
    "arm", "det_id8", "label", "request_id", "day", "first", "last",
    "n_frames", "n_crops", "prompt", "polygon", "prior_ctx",
    "disposal", "confidence", "waste_type", "offender_detected",
    "evidence_summary", "cost_usd", "latency_ms", "model", "error",
]

_csv_lock = threading.Lock()
_progress = {"done": 0, "total": 0, "cost": 0.0}


# ── índice de frames + janelas ───────────────────────────────────────────────
def frame_index() -> dict[str, Path]:
    """Índice GLOBAL por nome de arquivo (janelas cruzam meia-noite/diretório)."""
    idx: dict[str, Path] = {}
    for d in sorted(DATA.glob("day*")):
        if d.is_dir():
            for p in d.rglob("*.jpg"):
                idx[p.name] = p
    return idx


def build_window(names_sorted: list[str], idx: dict[str, Path],
                 first: str, last: str) -> list[Path]:
    """Todos os frames com first <= nome <= last (ordem cronológica = ordem do nome)."""
    import bisect
    lo = bisect.bisect_left(names_sorted, first)
    hi = bisect.bisect_right(names_sorted, last)
    return [idx[n] for n in names_sorted[lo:hi]]


def load_rows(labels: tuple[str, ...]) -> list[dict]:
    with open(RESULTS / "manifest.csv", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["label"] in labels]


# ── crops: espelho verbatim de main._process_with_gemini (main.py:822-884) ───
def build_pile_crops(sequence_paths: list[Path], polygon, out_dir: Path) -> list[Path]:
    """Mesma seleção/bbox/upscale de prod. Usa as funções REAIS do worker."""
    if len(sequence_paths) < 2:
        return []
    bbox = wmain._pile_bbox(polygon) if polygon else None
    if not bbox:
        return []
    n_target = min(max(1, cfg.GEMINI_DETAIL_PILECROP_N_FRAMES), len(sequence_paths))
    if n_target > 1:
        idxs = [
            int(round(i * (len(sequence_paths) - 1) / (n_target - 1)))
            for i in range(n_target)
        ]
    else:
        idxs = [0]
    crop_inputs = [sequence_paths[k] for k in idxs]
    return wmain._make_pile_crops(
        crop_inputs, bbox, cfg.GEMINI_DETAIL_PILECROP_UPSCALE, out_dir
    )


def camera_context() -> dict[str, str]:
    """Idêntico a main._process_with_gemini (main.py:808-814) — sem horario_local."""
    return {
        "camera_name": CAMERA_ROW["name"],
        "device_id": DEVICE_ID,
        "logradouro": CAMERA_ROW["logradouro"],
        "bairro": CAMERA_ROW["bairro"],
        "rpa": CAMERA_ROW["rpa"],
    }


def prior_ctx_text(had: bool, waste: str | None) -> str | None:
    """Idêntico a main.py:1379-1384."""
    if not had:
        return None
    label = f" (type: {waste})" if waste else ""
    return (
        f"- The previous 2-minute window ALREADY had waste at this location{label}. "
        "Confirm NEW_SOLID_WASTE only if a NEW object appeared or the volume visibly increased."
    )


# ── prior state (opcional): reconstrói last_window_had_litter via gate real ──
def probe_prior_state(rows: list[dict], idx: dict[str, Path], names: list[str],
                      workers: int) -> dict[str, dict]:
    """Roda o gate (flash-lite, ~$0.0015/janela) na janela ANTERIOR de cada rótulo
    para recuperar last_frame_has_litter + waste_type — o estado que prod passa ao
    detail como prior_window_context (main.py:1362-1364, gravado em main.py:1626).

    Aproximação documentada: o gate da janela anterior roda com prior=None
    (profundidade 1, sem recursão) e first_frame = primeiro frame da própria
    janela anterior. last_frame_has_litter é um fato sobre o ÚLTIMO frame, então
    é robusto a essas duas escolhas.
    """
    cache: dict[str, dict] = {}
    if PRIOR_PATH.exists():
        cache = json.loads(PRIOR_PATH.read_text(encoding="utf-8"))

    # audit completo em ordem cronológica → janela anterior de cada rótulo
    with open(RESULTS / "manifest.csv", encoding="utf-8") as fh:
        allrows = list(csv.DictReader(fh))
    allrows.sort(key=lambda r: (r["first"], r["last"]))
    pos = {r["request_id"]: i for i, r in enumerate(allrows)}

    todo = []
    for r in rows:
        if r["request_id"] in cache:
            continue
        i = pos[r["request_id"]]
        if i == 0:
            cache[r["request_id"]] = {"had": False, "waste": None, "src": "no_previous"}
            continue
        todo.append((r["request_id"], allrows[i - 1]))

    if not todo:
        return cache
    print(f"[prior] probing gate em {len(todo)} janelas anteriores (~${len(todo)*0.0015:.2f})")

    cam = SimpleNamespace(**CAMERA_ROW, pile_zone_polygon=POLYGONS["current"])

    def one(item):
        rid, prev = item
        win = build_window(names, idx, prev["first"], prev["last"])
        if len(win) < 2:
            return rid, {"had": False, "waste": None, "src": "prev_window_missing"}
        n = len(win)
        mids = None
        mid_count = max(0, cfg.GEMINI_GATE_MID_FRAMES)
        if n >= 3 and mid_count > 0:
            step = (n - 1) / (mid_count + 1)
            ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
            ks = [k for k in ks if 0 < k < n - 1]
            if ks:
                mids = [win[k] for k in ks]
        try:
            g = call_with_backoff(
                lambda: analyze_new_litter_with_gemini(
                    first_frame=win[0], last_frame=win[-1],
                    camera_context={**camera_context(), "horario_local": ""},
                    request_id=str(uuid4()), prior_window_context=None,
                    use_mosaic=cfg.GEMINI_MOSAIC_AGENT1, mid_frames=mids,
                    prompt_version=cfg.GEMINI_PROMPT_VERSION,
                )
            )
            return rid, {
                "had": bool(g.report.last_frame_has_litter),
                "waste": g.report.waste_type,
                "src": "gate_probe",
            }
        except Exception as exc:  # noqa: BLE001
            return rid, {"had": False, "waste": None, "src": f"error: {exc}"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed([pool.submit(one, t) for t in todo]):
            rid, val = fut.result()
            cache[rid] = val
    PRIOR_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    n_had = sum(1 for v in cache.values() if v.get("had"))
    print(f"[prior] last_window_had_litter=True em {n_had}/{len(cache)} janelas")
    return cache


# ── chamada com backoff externo (429/503) ────────────────────────────────────
def call_with_backoff(fn, tries: int = 5):
    """analyze_* já tem o retry INTERNO de prod (GEMINI_MAX_RETRIES=2, backoff 1-2s).
    Este laço externo é só do bench: aguenta 429/quota sem mudar o input do modelo."""
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            transient = any(
                t in msg for t in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500")
            )
            if not transient or attempt == tries:
                raise
            sleep = min(120, 10 * 2 ** (attempt - 1)) * (0.7 + 0.6 * random.random())
            print(f"[backoff] {msg[:70]} — retry {attempt}/{tries-1} em {sleep:.0f}s")
            time.sleep(sleep)


# ── execução de 1 janela × 1 braço ───────────────────────────────────────────
def run_one(row: dict, arm: str, idx: dict[str, Path], names: list[str],
            prior: dict, dry: bool) -> dict:
    spec = ARMS[arm]
    win = build_window(names, idx, row["first"], row["last"])
    expected = int(row["window_size"])
    if len(win) != expected:
        raise RuntimeError(
            f"janela != prod: {len(win)} frames vs window_size={expected} "
            f"({row['first']} .. {row['last']}) — input NÃO replica prod, abortando"
        )
    win = event_windows.fit_frames_to_payload(win, cfg.GEMINI_MAX_PAYLOAD_BYTES)

    poly = POLYGONS[spec["polygon"]] if spec["polygon"] else None
    pctx = prior.get(row["request_id"], {})
    ctx_text = prior_ctx_text(bool(pctx.get("had")), pctx.get("waste"))

    tmp_dir: Path | None = None
    rec = {
        "arm": arm, "det_id8": row["det_id8"], "label": row["label"],
        "request_id": row["request_id"], "day": row["day"],
        "first": row["first"], "last": row["last"], "n_frames": len(win),
        "polygon": spec["polygon"] or "", "prior_ctx": int(bool(ctx_text)),
        "model": cfg.GEMINI_MODEL,
    }
    try:
        crops: list[Path] = []
        if poly:
            tmp_dir = Path(tempfile.mkdtemp(prefix=f"camp45_{arm}_"))
            crops = build_pile_crops(win, poly, tmp_dir)
            if not crops:
                raise RuntimeError("pile crops vazios (bbox inválido?)")
        rec["n_crops"] = len(crops)

        # Seleção de prompt = mecanismo de prod (_prompts_v3.detail_system_prompt_for_camera
        # lê DETAIL_HIGHBAR_DEVICES do env em tempo de chamada; setado por braço no main()).
        prompt_version = "mangabeira_with_pilecrops" if crops else "v3"
        sysprompt = p3.detail_system_prompt_for_camera(
            camera_context(), has_pilecrops=bool(crops)
        )
        name_by_text = {
            p3.DETAIL_PROMPT_MANGABEIRA_HIGHBAR: "DETAIL_PROMPT_MANGABEIRA_HIGHBAR",
            p3.DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS:
                "DETAIL_PROMPT_MANGABEIRA_E_WITH_PILECROPS",
            p3.SYSTEM_PROMPT_V3: "SYSTEM_PROMPT_V3",
        }
        got = name_by_text.get(sysprompt, "?")
        if got != spec["prompt"]:
            raise RuntimeError(f"prompt errado no braço {arm}: {got} != {spec['prompt']}")
        rec["prompt"] = got

        if dry:
            payload = sum(p.stat().st_size for p in win) + sum(c.stat().st_size for c in crops)
            rec.update({"disposal": "", "confidence": "", "waste_type": "",
                        "offender_detected": "", "evidence_summary": "",
                        "cost_usd": 0.0, "latency_ms": payload, "error": ""})
            return rec

        res = call_with_backoff(
            lambda: analyze_with_gemini(
                image_paths=win,
                camera_context=camera_context(),
                request_id=str(uuid4()),
                mosaic_mode=cfg.GEMINI_MOSAIC_AGENT2,
                prior_window_context=ctx_text,
                prompt_version=prompt_version,
                pile_crops=crops or None,
            )
        )
        rep = res.report
        rec.update({
            "disposal": int(bool(rep.infraction_confirmed)),
            "confidence": int(getattr(rep, "confidence_0_100", 0) or 0),
            "waste_type": getattr(rep, "waste_type", "") or "",
            "offender_detected": getattr(rep, "offender_detected", ""),
            "evidence_summary": (getattr(rep, "evidence_summary", "") or "").replace("\n", " "),
            "cost_usd": float(res.usage.estimated_cost_usd or 0.0),
            "latency_ms": int(res.latency_ms), "error": "",
        })
        return rec
    except Exception as exc:  # noqa: BLE001
        rec.update({"disposal": "", "confidence": "", "waste_type": "",
                    "offender_detected": "", "evidence_summary": "", "cost_usd": 0.0,
                    "latency_ms": "", "n_crops": rec.get("n_crops", ""),
                    "prompt": rec.get("prompt", ""), "error": str(exc)[:300]})
        return rec
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def append_csv(rec: dict) -> None:
    with _csv_lock:
        new = not CSV_PATH.exists()
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_COLS)
            if new:
                w.writeheader()
            w.writerow({k: rec.get(k, "") for k in CSV_COLS})
        _progress["done"] += 1
        _progress["cost"] += float(rec.get("cost_usd") or 0)
        if _progress["done"] % 10 == 0 or _progress["done"] == _progress["total"]:
            print(f"  [{_progress['done']}/{_progress['total']}] "
                  f"custo acumulado ${_progress['cost']:.2f}", flush=True)


def done_keys() -> set[tuple[str, str]]:
    if not CSV_PATH.exists():
        return set()
    with open(CSV_PATH, encoding="utf-8") as fh:
        return {(r["arm"], r["request_id"]) for r in csv.DictReader(fh) if not r["error"]}


# ── agregação ────────────────────────────────────────────────────────────────
def aggregate() -> dict:
    with open(CSV_PATH, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)]
    ok = [r for r in rows if r["disposal"] in ("0", "1")]
    summary: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": cfg.GEMINI_MODEL,
        "note_subset": (
            "As 153 janelas rotuladas são, por construção, janelas em que o Agent-2 "
            "de PROD confirmou (disposal=true). A taxa de rejeição abaixo é sobre esse "
            "subset (% das confirmações de prod que o braço mataria), NÃO é a taxa "
            "fleet-wide de 52,8%/73,9% do audit — para essa, rodar --include-trig."
        ),
        "arms": {},
    }
    for arm in sorted({r["arm"] for r in ok}):
        a = [r for r in ok if r["arm"] == arm]
        lab = [r for r in a if r["label"] in ("CONF", "REJ")]
        conf_w = [r for r in lab if r["label"] == "CONF"]
        rej_w = [r for r in lab if r["label"] == "REJ"]

        def by_det(rs):
            d: dict[str, bool] = {}
            for r in rs:
                d[r["det_id8"]] = d.get(r["det_id8"], False) or r["disposal"] == "1"
            return d

        conf_d, rej_d = by_det(conf_w), by_det(rej_w)
        kept = sum(1 for v in conf_d.values() if v)
        killed = sum(1 for v in rej_d.values() if not v)
        lost = sorted([k for k, v in conf_d.items() if not v])
        lost_detail = []
        for det in lost:
            for r in conf_w:
                if r["det_id8"] == det:
                    lost_detail.append({
                        "det_id8": det, "request_id": r["request_id"], "brt_first": r["first"],
                        "confidence": r["confidence"],
                        "evidence_summary": r["evidence_summary"],
                    })
        costs = [float(r["cost_usd"]) for r in a if r["cost_usd"]]
        lats = [int(r["latency_ms"]) for r in a if r["latency_ms"]]
        w_true = sum(1 for r in lab if r["disposal"] == "1")
        summary["arms"][arm] = {
            "desc": ARMS[arm]["desc"], "prompt": ARMS[arm]["prompt"],
            "polygon": ARMS[arm]["polygon"], "n_windows": len(lab),
            "detections": {"conf_total": len(conf_d), "conf_kept": kept,
                           "conf_lost": len(conf_d) - kept,
                           "rej_total": len(rej_d), "rej_killed": killed,
                           "rej_survived": len(rej_d) - killed},
            "recall_conf_pct": round(100 * kept / len(conf_d), 1) if conf_d else None,
            "rej_killed_pct": round(100 * killed / len(rej_d), 1) if rej_d else None,
            "hard_criterion_pass": bool(conf_d) and kept == len(conf_d),
            "windows": {"total": len(lab), "disposal_true": w_true,
                        "disposal_false": len(lab) - w_true,
                        "rejection_rate_pct_on_subset":
                            round(100 * (len(lab) - w_true) / len(lab), 1) if lab else None},
            "confusion_by_detection": {
                "CONF_kept_TP": kept, "CONF_lost_FN": len(conf_d) - kept,
                "REJ_survived_FP": len(rej_d) - killed, "REJ_killed_TN": killed,
            },
            "cost_usd_total": round(sum(costs), 4),
            "cost_usd_per_window": round(sum(costs) / len(costs), 5) if costs else None,
            "latency_ms_p50": int(statistics.median(lats)) if lats else None,
            "conf_lost_details": lost_detail,
            "errors": sum(1 for r in rows if r["arm"] == arm and r["error"]),
        }
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    SECTION_PATH.write_text(render_section(summary), encoding="utf-8")
    return summary


def render_section(s: dict) -> str:
    L = ["## A/B offline do Agent-2 (detail) — pilecrops + HIGHBAR vs prod atual", ""]
    L.append("Braços rodados sobre as **153 janelas rotuladas** do audit pós-mudança "
             "(14 janelas CONF = 12 detecções · 139 janelas REJ = 116 detecções). "
             "Input replicado 1:1 do que prod mandou (janela contígua do audit, "
             "`window_size` conferido janela a janela; chamada via "
             "`detector_gemini.analyze_with_gemini`).")
    L += ["", "| Braço | Config | CONF mantidas (dur: 12/12) | REJ mortas /116 | "
              "Rejeição no subset | $/janela | p50 (ms) |",
          "|---|---|---|---|---|---|---|"]
    for arm in sorted(s["arms"]):
        a = s["arms"][arm]
        d = a["detections"]
        flag = "✅" if a["hard_criterion_pass"] else "❌"
        L.append(
            f"| **{arm}** | {a['desc']} | {flag} {d['conf_kept']}/{d['conf_total']} "
            f"({a['recall_conf_pct']}%) | {d['rej_killed']}/{d['rej_total']} "
            f"({a['rej_killed_pct']}%) | {a['windows']['rejection_rate_pct_on_subset']}% | "
            f"${a['cost_usd_per_window']} | {a['latency_ms_p50']} |"
        )
    L += ["", "> ⚠️ A coluna *Rejeição no subset* é a % das janelas que **prod confirmou** "
              "e o braço mataria. Não é comparável direto com os 73,9% (antes) / 52,8% "
              "(hoje) do audit, que são sobre todas as chamadas do Agent-2.", ""]
    for arm in sorted(s["arms"]):
        a = s["arms"][arm]
        if a["conf_lost_details"]:
            L.append(f"**CONF perdidas no braço {arm}:**")
            L.append("")
            for d in a["conf_lost_details"]:
                L.append(f"- `{d['det_id8']}` ({d['brt_first']}) — conf {d['confidence']}: "
                         f"_{d['evidence_summary']}_")
            L.append("")
    return "\n".join(L)


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="A,B,C")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="valida input, zero chamadas")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--aggregate-only", action="store_true")
    ap.add_argument("--prior-mode", choices=["probe", "none"], default="probe",
                    help="probe = reconstrói prior_window_context via gate (~$0.25 uma vez)")
    ap.add_argument("--include-trig", action="store_true",
                    help="inclui as 189 janelas TRIG_NOLABEL (taxa de rejeição fleet-wide)")
    args = ap.parse_args()

    if args.aggregate_only:
        s = aggregate()
        print(json.dumps({k: v for k, v in s["arms"].items()}, ensure_ascii=False, indent=2)[:2500])
        print(f"\n→ {SUMMARY_PATH}\n→ {SECTION_PATH}")
        return 0

    labels = ("CONF", "REJ") + (("TRIG_NOLABEL",) if args.include_trig else ())
    rows = load_rows(labels)
    if args.limit:
        rows = rows[: args.limit]
    idx = frame_index()
    names = sorted(idx)
    arms = [a.strip().upper() for a in args.arms.split(",") if a.strip()]

    print(f"[cfg] model={cfg.GEMINI_MODEL} mosaic_agent2={cfg.GEMINI_MOSAIC_AGENT2!r} "
          f"max_out={cfg.GEMINI_MAX_OUTPUT_TOKENS} timeout={cfg.GEMINI_TIMEOUT_SECONDS}s "
          f"retries={cfg.GEMINI_MAX_RETRIES} temp={cfg.GEMINI_TEMPERATURE} "
          f"crops_n={cfg.GEMINI_DETAIL_PILECROP_N_FRAMES} up={cfg.GEMINI_DETAIL_PILECROP_UPSCALE}")
    print(f"[cfg] vertex={cfg.GEMINI_USE_VERTEX} project={cfg.GCP_PROJECT} "
          f"location={cfg.GCP_LOCATION}")
    print(f"[data] {len(idx)} frames | {len(rows)} janelas | braços {arms}")

    prior: dict = {}
    if args.prior_mode == "probe" and not args.dry_run:
        prior = probe_prior_state(rows, idx, names, args.workers)
    elif args.prior_mode == "probe" and args.dry_run and PRIOR_PATH.exists():
        prior = json.loads(PRIOR_PATH.read_text(encoding="utf-8"))

    skip = done_keys()
    for arm in arms:
        # Mecanismo real de seleção do HIGHBAR (lido em tempo de chamada).
        os.environ["DETAIL_HIGHBAR_DEVICES"] = "esp32_002" if ARMS[arm]["highbar"] else ""
        todo = [r for r in rows if (arm, r["request_id"]) not in skip]
        _progress.update({"done": 0, "total": len(todo), "cost": 0.0})
        print(f"\n=== braço {arm}: {ARMS[arm]['desc']} — {len(todo)} janelas "
              f"({len(rows)-len(todo)} já no CSV) ===")
        if not todo:
            continue
        if args.dry_run:
            sizes = []
            for r in todo:
                rec = run_one(r, arm, idx, names, prior, dry=True)
                if rec["error"]:
                    print(f"  ERRO {r['request_id'][:8]}: {rec['error']}")
                    return 1
                sizes.append(rec["latency_ms"])
            print(f"  OK — prompt={ARMS[arm]['prompt']} "
                  f"crops/janela={rec['n_crops']} "
                  f"payload MB: min={min(sizes)/1e6:.2f} med={statistics.median(sizes)/1e6:.2f} "
                  f"max={max(sizes)/1e6:.2f} (teto {cfg.GEMINI_MAX_PAYLOAD_BYTES/1e6:.1f})")
            if max(sizes) > cfg.GEMINI_MAX_PAYLOAD_BYTES:
                print("  ⚠️ payload acima do teto — prod trimaria a janela")
            continue
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(run_one, r, arm, idx, names, prior, False) for r in todo]
            for fut in as_completed(futs):
                append_csv(fut.result())

    if args.dry_run:
        print("\n[dry-run] input validado janela a janela contra window_size do audit.")
        return 0
    s = aggregate()
    for arm in sorted(s["arms"]):
        a = s["arms"][arm]
        print(f"{arm}: CONF {a['detections']['conf_kept']}/{a['detections']['conf_total']} "
              f"| REJ mortas {a['detections']['rej_killed']}/{a['detections']['rej_total']} "
              f"| ${a['cost_usd_total']:.2f}")
    print(f"\n→ {CSV_PATH}\n→ {SUMMARY_PATH}\n→ {SECTION_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
