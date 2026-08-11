#!/usr/bin/env python3
"""Camp 48 — Fase B: VLMs open-weight do Bedrock vs controle Gemini-2.5, cam_picam001.

Fork de `47-picam001-model-migration/scripts/bench_picam.py`. Preserva verbatim o que
define a fidelidade (janela, mids, métricas detection-level, resumabilidade) e troca
apenas o transporte para o Bedrock Converse via `_bedrock_client`.

Só roda sobre eventos APROVADOS na Fase 0 (`_review_camp48/INDEX.csv`). Se sobrar
pendência (VALID em branco), o script recusa rodar — meio-validado gera número que
ninguém sabe interpretar depois.

Uso:
    python scripts/bench_bedrock.py --arms current --limit 3 --dry-run
    python scripts/bench_bedrock.py --arms current                      # controle
    python scripts/bench_bedrock.py --arms gemma-3-27b:casc_v1,gemma-3-27b:single_g3
    python scripts/bench_bedrock.py --aggregate-only
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
OFFICIAL = ROOT / "data" / "datasets" / "official"
CAM = OFFICIAL / "cam_picam001"
REVIEW_INDEX = CAM / "_review_camp48" / "INDEX.csv"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
CSV_PATH = RESULTS / "bench_bedrock.csv"
SUMMARY_PATH = RESULTS / "bench_bedrock_summary.json"

# ── PROD-exact window env, ANTES de worker.config (bench_picam.py:65-79) ─────
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

# O controle Gemini exige a chave de teste; os braços Bedrock não.
_TEST_KEY = os.environ.get("GEMINI_TEST_API_KEY", "").strip()
if _TEST_KEY:
    os.environ["GEMINI_USE_VERTEX"] = "false"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
    os.environ["GEMINI_API_KEY"] = _TEST_KEY

sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker.config as cfg                     # noqa: E402
import worker.event_windows as event_windows    # noqa: E402
import worker.detector_gemini as dg             # noqa: E402
import worker.mosaic as mosaic                  # noqa: E402
import worker._prompts_g3 as p_g3               # noqa: E402
from worker.schemas_gemini import (             # noqa: E402
    GeminiInfractionReport, GeminiNewLitterReport,
)
import _bedrock_client as bc                    # noqa: E402

CAMERA_ROW = {"name": "Residencial Via Mangue III - 2", "device_id": "pi-cam-001",
              "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
              "bairro": "Imbiribeira", "rpa": "RPA-1"}
DEVICE_ID = "pi-cam-001"
TRIGGER_THR = 85
# Tabela de PRODUÇÃO (`detector_gemini._MODEL_PRICES`:676) — é a que reflete a fatura.
# ATENÇÃO: o runner do Camp 47 usou (0.15, 0.60) para o 2.5-flash (bench_picam.py:351),
# subestimando o OUTPUT em ~4x. Como o detail pensa ~3k tokens/evento e thinking é
# cobrado como output, o custo de $0,00099/ev que o Camp 47 reportou para o braço
# `current` está SUBESTIMADO. Números de custo desta campanha não são comparáveis
# aos daquele report sem recomputar dos tokens crus (é o que agg_all.py faz).
GEMINI_PRICE = {"gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.30, 2.50)}

# ── Braços ───────────────────────────────────────────────────────────────────
# Bedrock: chave "<alias>:<perfil>". Gemini: "current" (controle).
#   casc_v1          2 estágios, janela cheia, prompt V1 (paridade prod)
#   casc_g3          2 estágios, janela cheia, prompt g3 (reasoning-first)
#   single_g3        1 chamada, janela cheia, prompt g3
#   single_g3_mosaic 1 chamada, mosaicos 4x3, prompt g3 (alavanca de custo)
# `img` = como as imagens do DETAIL/single são codificadas. O gate manda sempre os
# 5 frames em resolução original (1,5 MB, cabe). O detail NÃO cabe em original: a
# janela mediana de prod tem 6,8 MB e o Bedrock corta em ~2,7 MB
# (ver _bedrock_client.MAX_RAW_BYTES) — por isso não existe braço `_orig`.
PROFILES = {
    "casc_v1_low":      {"stages": 2, "prompt": "v1", "img": "low"},
    "casc_g3_low":      {"stages": 2, "prompt": "g3", "img": "low"},
    "single_g3_low":    {"stages": 1, "prompt": "g3", "img": "low"},
    "single_g3_mosaic": {"stages": 1, "prompt": "g3", "img": "mosaic"},
}
GEMINI_ARMS = {
    "current": {"provider": "gemini", "gate": "gemini-2.5-flash-lite",
                "detail": "gemini-2.5-flash", "prompt": "v1"},
}


def resolve_arm(name: str) -> dict:
    if name in GEMINI_ARMS:
        return dict(GEMINI_ARMS[name], name=name)
    if ":" not in name:
        raise SystemExit(f"braço '{name}' desconhecido — use '<alias>:<perfil>' "
                         f"(aliases: {sorted(a for a in bc.MODELS if a not in bc.ELIMINATED)}; "
                         f"perfis: {sorted(PROFILES)}) ou {sorted(GEMINI_ARMS)}")
    alias, prof = name.split(":", 1)
    if alias not in bc.MODELS:
        raise SystemExit(f"alias '{alias}' desconhecido")
    if alias in bc.ELIMINATED:
        raise SystemExit(f"alias '{alias}' foi ELIMINADO pelo probe: {bc.MODELS[alias].note}")
    if prof not in PROFILES:
        raise SystemExit(f"perfil '{prof}' desconhecido — {sorted(PROFILES)}")
    return dict(PROFILES[prof], provider="bedrock", alias=alias, name=name,
                gate=alias, detail=alias)


# ── Fase 0: portão de validação humana ───────────────────────────────────────
def load_review(strict=True) -> set[str]:
    """Retorna os event_ids EXCLUÍDOS pelo operador. Falha se houver pendência."""
    if not REVIEW_INDEX.exists():
        raise SystemExit(f"Fase 0 não rodada: {REVIEW_INDEX} não existe.\n"
                         f"rode: python scripts/export_review.py")
    rows = list(csv.DictReader(REVIEW_INDEX.open(encoding="utf-8-sig")))
    pend = [r["event_id"] for r in rows if (r.get("VALID") or "").strip().lower()
            not in ("y", "n", "s", "yes", "no", "sim", "nao", "não")]
    if pend and strict:
        raise SystemExit(
            f"{len(pend)} de {len(rows)} eventos sem veredicto em {REVIEW_INDEX.name}.\n"
            f"Preencha VALID (y/n) em todos antes de rodar. Pendentes: "
            f"{', '.join(pend[:8])}{'…' if len(pend) > 8 else ''}")
    excl = {r["event_id"] for r in rows
            if (r.get("VALID") or "").strip().lower() in ("n", "no", "nao", "não")}
    return excl


def load_events(limit=None, cats=None, excluded=frozenset()):
    """Verbatim de bench_picam.py:357, + filtro da Fase 0."""
    rows = []
    for cat in ("tp", "fp", "indefinido", "baseline"):
        if cats and cat not in cats:
            continue
        for lab in sorted((CAM / cat).glob("*/label.json")):
            L = json.loads(lab.read_text(encoding="utf-8"))
            if L["event_id"] in excluded:
                continue
            frames = sorted((lab.parent / "frames").glob("*.jpg"))
            if len(frames) < 2:
                continue
            rows.append({"event_id": L["event_id"], "category": cat,
                         "frames": frames, "datetime": L.get("datetime", ""),
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


# ── janela: verbatim de bench_picam.py:395-409 ───────────────────────────────
def gate_mids(win):
    n = len(win)
    mid_count = max(0, cfg.GEMINI_GATE_MID_FRAMES)
    if n < 3 or mid_count == 0:
        return None
    step = (n - 1) / (mid_count + 1)
    ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
    ks = [k for k in ks if 0 < k < n - 1]
    return [win[k] for k in ks] or None


def build_window(frames):
    win = event_windows.subsample_frames(frames, cfg.GEMINI_CASCADE_MAX_FRAMES)
    win = event_windows.fit_frames_to_payload(win, cfg.GEMINI_MAX_PAYLOAD_BYTES)
    return win


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


# ── mosaico: N frames -> ceil(N/12) folhas 4x3, rótulos contínuos 1..N ───────
# `mosaic.build_mosaic_4x3` TRUNCA em 12 frames (mosaic.py:94), o que perderia o
# depósito numa janela de 48. Aqui fatio em blocos de 12 e uso label_offset para os
# rótulos correrem 1..N, reusando o grid de produção (resize/pad/label).
def build_mosaic_sheets(frames: list[Path], cols=3, rows=4) -> list[Path]:
    import cv2
    per = cols * rows
    out = []
    for start in range(0, len(frames), per):
        chunk = frames[start:start + per]
        grid = mosaic._build_grid(chunk, cols=cols, rows=rows,
                                  cell_height=240, label_offset=start)
        tmp = tempfile.NamedTemporaryFile(suffix=f"_c48_mosaic_{start:03d}.jpg", delete=False)
        tmp.close()
        cv2.imwrite(tmp.name, grid, [cv2.IMWRITE_JPEG_QUALITY, 85])
        out.append(Path(tmp.name))
    return out


def mosaic_user_prompt(cc: dict, n_frames: int, n_sheets: int) -> str:
    """Prod descreve UMA folha de 12 (`_user_prompt`, mosaic_mode='4x3'); aqui podem
    ser várias, então a descrição das imagens é local a esta campanha."""
    ctx = "\n".join(f"- {k}: {v}" for k, v in cc.items() if v) or "- sem contexto adicional"
    return (
        "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
        "1) confirmacao de infracao\n"
        "2) confianca 0..100\n"
        "3) resumo factual curto da evidencia\n"
        "4) classificacao de residuo/material e volume aproximado\n"
        "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
        "6) event_frame_name e offender_frame_name usando o formato 'frame_N'\n"
        "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com "
        "offender_detected=false.\n"
        f"Formato das imagens: {n_sheets} mosaico(s) de 4 linhas x 3 colunas, "
        f"cada celula rotulada com seu numero. As celulas cobrem os frames 1 a {n_frames} "
        "em ordem cronologica (o mosaico 1 traz 1-12, o 2 traz 13-24, e assim por diante). "
        f"Frame 1 e o mais antigo, frame {n_frames} o mais recente. "
        "Use 'frame_N' como event_frame_name e offender_frame_name.\n"
        "Contexto da camera:\n"
        f"{ctx}"
    )


# ── post-gate determinístico de produção (detector_gemini.py:1239-1276) ─────
def apply_v1_gate(report) -> object:
    """Prod aplica isso DENTRO de analyze_new_litter_with_gemini. Para o Bedrock
    tenho que aplicar aqui, senão o candidato levaria vantagem artificial (o Gemini
    passa pelo filtro e ele não)."""
    scene = (getattr(report, "scene_type", "") or "").upper().strip()
    if scene != "DUMPING" and report.new_litter_detected:
        report.new_litter_detected = False
        report.confidence_0_100 = 0
    bool_count = sum([
        bool(getattr(report, "vehicle_stopped", False)),
        bool(getattr(report, "person_handling_material", False)),
        bool(getattr(report, "new_ground_material", False)),
    ])
    if report.new_litter_detected and bool_count < 2:
        report.new_litter_detected = False
        report.confidence_0_100 = 0
    if not report.new_litter_detected and scene == "DUMPING" and bool_count >= 2:
        report.new_litter_detected = True
        report.confidence_0_100 = max(report.confidence_0_100, 85)
    return report


def prompts_for(kind: str, version: str) -> str:
    if kind == "gate":
        return p_g3.G3_GATE_PROMPT if version == "g3" else dg.NEW_LITTER_SYSTEM_PROMPT
    return p_g3.G3_DETAIL_PROMPT if version == "g3" else dg.SYSTEM_PROMPT


COLS = ["arm", "provider", "model_id", "event_id", "det_id", "category",
        "n_raw", "n_window", "n_images_sent", "img_mode", "n_dropped_payload",
        "payload_mb", "gate_model", "detail_model", "prompt", "json_mode",
        "json_valid", "gate_fire", "gate_conf", "disposal", "detail_conf",
        "waste_type", "evidence", "tok_in", "tok_out", "tok_think", "cost_usd",
        "latency_ms", "error"]


def blank_rec(ev, arm, spec, win):
    return {"arm": arm, "provider": spec["provider"],
            "model_id": bc.MODELS[spec["alias"]].model_id if spec["provider"] == "bedrock" else "",
            "event_id": ev["event_id"], "det_id": ev["det_id"], "category": ev["category"],
            "n_raw": len(ev["frames"]), "n_window": len(win), "n_images_sent": "",
            "img_mode": spec.get("img", ""), "n_dropped_payload": "", "payload_mb": "",
            "gate_model": spec["gate"],
            "detail_model": spec["detail"], "prompt": spec.get("prompt", "v1"),
            "json_mode": "", "json_valid": "", "gate_fire": "", "gate_conf": "",
            "disposal": "", "detail_conf": "", "waste_type": "",
            "tok_in": "", "tok_out": "", "tok_think": "", "cost_usd": 0.0,
            "latency_ms": "", "error": ""}


def run_bedrock(ev, spec, win, rec):
    alias = spec["alias"]
    cc = camera_context(win)
    pv = spec["prompt"]
    img_mode = spec.get("img", "low")
    tmps: list[Path] = []
    t0 = time.time()
    try:
        if img_mode == "mosaic":
            sheets = build_mosaic_sheets(win)
            tmps += sheets
            dpay = bc.prepare_images(sheets, mode="orig")
            duser = mosaic_user_prompt(cc, len(win), dpay.n_images)
        else:
            dpay = bc.prepare_images(win, mode=img_mode)
            # Se o teto do Bedrock cortou frames, os nomes permitidos têm que
            # refletir o que foi realmente enviado — senão o modelo devolve um
            # event_frame_name que não existe na requisição.
            names = [p.name for p in win]
            if dpay.n_dropped:
                names = [p.name for p in bc._even_drop(win, dpay.n_images)]
            duser = dg._user_prompt(camera_context=cc, frame_names=names,
                                    mosaic_mode="off", prior_window_context=None)
        rec["n_dropped_payload"] = dpay.n_dropped
        rec["img_mode"] = img_mode
        rec["payload_mb"] = round(dpay.raw_bytes / 1e6, 2)

        tin = tout = 0
        cost_total = 0.0

        if spec["stages"] == 2:
            gframes = [win[0]] + (gate_mids(win) or []) + [win[-1]]
            gpay = bc.prepare_images(gframes, mode="orig")
            guser = dg._new_litter_user_prompt(
                first_frame_name=win[0].name, last_frame_name=win[-1].name,
                camera_context=cc, prior_window_context=None, mosaic=False,
                mid_frame_names=[p.name for p in (gate_mids(win) or [])])
            g = bc.converse(alias, prompts_for("gate", pv), guser, gpay.blobs,
                            GeminiNewLitterReport, max_tokens=8192)
            rec.update({"json_mode": g.json_mode, "json_valid": int(g.json_valid),
                        "n_images_sent": g.n_images})
            tin, tout, cost_total = g.tok_in, g.tok_out, g.cost_usd
            if not g.json_valid:
                rec["error"] = f"gate: {g.error}"
                return rec
            gr = apply_v1_gate(g.report)
            fire = bool(gr.new_litter_detected) and int(gr.confidence_0_100) >= TRIGGER_THR
            rec.update({"gate_fire": int(fire), "gate_conf": int(gr.confidence_0_100),
                        "evidence": (getattr(gr, "evidence_summary", "") or "")[:300]})
            if not fire:
                rec["disposal"] = 0
                rec.update({"tok_in": tin, "tok_out": tout, "tok_think": 0,
                            "cost_usd": round(cost_total, 6),
                            "latency_ms": int((time.time() - t0) * 1000)})
                return rec

        d = bc.converse(alias, prompts_for("detail", pv), duser, dpay.blobs,
                        GeminiInfractionReport, max_tokens=8192)
        tin += d.tok_in
        tout += d.tok_out
        cost_total += d.cost_usd
        rec.update({"json_mode": d.json_mode or rec["json_mode"],
                    "json_valid": int(d.json_valid), "n_images_sent": d.n_images,
                    "tok_in": tin, "tok_out": tout, "tok_think": 0,
                    "cost_usd": round(cost_total, 6),
                    "latency_ms": int((time.time() - t0) * 1000)})
        if not d.json_valid:
            rec["error"] = f"detail: {d.error}"
            return rec
        dr = d.report
        disp = int(bool(dr.infraction_confirmed))
        rec.update({"disposal": disp,
                    "detail_conf": int(getattr(dr, "confidence_0_100", 0) or 0),
                    "waste_type": getattr(dr, "waste_type", "") or "",
                    "evidence": (getattr(dr, "evidence_summary", "") or "")[:300]})
        if spec["stages"] == 1:
            rec["gate_fire"] = disp
    except Exception as exc:  # noqa
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
    finally:
        for p in tmps:
            try:
                p.unlink()
            except OSError:
                pass
    return rec


def usage_tokens(usage):
    """Verbatim de bench_picam.py:412 — thinking é cobrado como OUTPUT no Gemini."""
    thk = int(getattr(usage, "thinking_tokens", 0)
              or getattr(usage, "thoughts_token_count", 0) or 0)
    for a, b in (("input_tokens", "output_tokens"),
                 ("prompt_token_count", "candidates_token_count")):
        i, o = getattr(usage, a, None), getattr(usage, b, None)
        if i is not None or o is not None:
            return int(i or 0), int(o or 0), thk
    return 0, 0, thk


def gcost(model, tin, tout, tthink=0):
    p = GEMINI_PRICE.get(model)
    return (tin / 1e6 * p[0] + (tout + tthink) / 1e6 * p[1]) if p else 0.0


def run_gemini(ev, spec, win, rec):
    """Controle: caminho de prod intocado (post-gates aplicados dentro das funções)."""
    cc = camera_context(win)
    t0 = time.time()
    try:
        g = dg.analyze_new_litter_with_gemini(
            first_frame=win[0], last_frame=win[-1], camera_context=cc,
            request_id=str(uuid4()), prior_window_context=None,
            use_mosaic=cfg.GEMINI_MOSAIC_AGENT1, mid_frames=gate_mids(win),
            prompt_version="current")
        gr = g.report
        gi, go, gt = usage_tokens(g.usage)
        c = gcost(spec["gate"], gi, go, gt)
        ti, to_, tt = gi, go, gt
        fire = bool(gr.new_litter_detected) and int(gr.confidence_0_100) >= TRIGGER_THR
        rec.update({"gate_fire": int(fire), "gate_conf": int(gr.confidence_0_100),
                    "json_valid": 1, "json_mode": "native",
                    "evidence": (getattr(gr, "evidence_summary", "") or "")[:300],
                    "n_images_sent": 2 + len(gate_mids(win) or [])})
        if fire:
            d = dg.analyze_with_gemini(
                image_paths=win, camera_context=cc, request_id=str(uuid4()),
                mosaic_mode=cfg.GEMINI_MOSAIC_AGENT2, prior_window_context=None,
                prompt_version="current")
            dr = d.report
            di, do, dt = usage_tokens(d.usage)
            c += gcost(spec["detail"], di, do, dt)
            ti, to_, tt = ti + di, to_ + do, tt + dt
            rec.update({"disposal": int(bool(dr.infraction_confirmed)),
                        "detail_conf": int(getattr(dr, "confidence_0_100", 0) or 0),
                        "waste_type": getattr(dr, "waste_type", "") or "",
                        "evidence": (getattr(dr, "evidence_summary", "") or "")[:300],
                        "n_images_sent": len(win)})
        else:
            rec["disposal"] = 0
        rec.update({"tok_in": ti, "tok_out": to_, "tok_think": tt,
                    "cost_usd": round(c, 6),
                    "latency_ms": int((time.time() - t0) * 1000)})
    except Exception as exc:  # noqa
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:250]}"
    return rec


def run_one(ev, arm_name, spec, dry=False):
    win = build_window(ev["frames"])
    rec = blank_rec(ev, arm_name, spec, win)
    if dry:
        if spec["provider"] == "bedrock":
            if spec.get("img") == "mosaic":
                sheets = build_mosaic_sheets(win)
                try:
                    pay = bc.prepare_images(sheets, mode="orig")
                finally:
                    for p in sheets:
                        try:
                            p.unlink()
                        except OSError:
                            pass
            else:
                pay = bc.prepare_images(win, mode=spec.get("img", "low"))
            rec.update({"n_images_sent": pay.n_images, "n_dropped_payload": pay.n_dropped,
                        "payload_mb": round(pay.raw_bytes / 1e6, 2)})
        else:
            rec.update({"n_images_sent": len(win),
                        "payload_mb": round(sum(p.stat().st_size for p in win) / 1e6, 2)})
        rec["latency_ms"] = sum(p.stat().st_size for p in win)   # payload bytes original
        rec["gate_conf"] = len([win[0]] + (gate_mids(win) or []) + [win[-1]])
        return rec
    if spec["provider"] == "bedrock":
        return run_bedrock(ev, spec, win, rec)
    return run_gemini(ev, spec, win, rec)


# ── CSV / métricas: verbatim de bench_picam.py:521-591, colunas estendidas ──
def append_csv(recs):
    new = not CSV_PATH.exists()
    if not new:
        existing = next(csv.reader(CSV_PATH.open(encoding="utf-8")), [])
        if existing and existing != COLS:
            raise SystemExit(f"CSV {CSV_PATH.name} tem cabeçalho diferente "
                             f"({len(existing)} col) do esperado ({len(COLS)} col) — "
                             f"use --tag novo ou apague o arquivo.")
    with CSV_PATH.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        for r in recs:
            w.writerow(r)


def done_keys():
    if not CSV_PATH.exists():
        return set()
    return {(r["arm"], r["event_id"])
            for r in csv.DictReader(CSV_PATH.open(encoding="utf-8"))}


def aggregate():
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        allr = [r for r in rows if r["arm"] == arm]
        ar = [r for r in allr if not r["error"]]

        def frac(cat, field="disposal", val=1):
            sub = [r for r in ar if r["category"] == cat]
            hit = [r for r in sub if str(r.get(field)) == str(val)]
            return len(hit), len(sub)

        def det_frac(cat):
            sub = [r for r in ar if r["category"] == cat]
            byd = {}
            for r in sub:
                byd.setdefault(r["det_id"], []).append(str(r.get("disposal")) == "1")
            return sum(1 for v in byd.values() if any(v)), len(byd)

        tp_fire, tp_n = frac("tp")
        fp_fire, fp_n = frac("fp")
        bl_fire, bl_n = frac("baseline")
        tp_dfire, tp_dn = det_frac("tp")
        fp_dfire, fp_dn = det_frac("fp")
        costs = [float(r["cost_usd"]) for r in ar if r["cost_usd"]]
        lats = sorted(int(r["latency_ms"]) for r in ar if str(r.get("latency_ms")).isdigit())
        jv = [r for r in allr if str(r.get("json_valid")) in ("0", "1")]
        out[arm] = {
            "n": len(ar), "n_errors": len(allr) - len(ar),
            "json_valid_rate": (round(100 * sum(1 for r in jv if r["json_valid"] == "1")
                                      / len(jv), 1) if jv else None),
            "json_mode": next((r["json_mode"] for r in allr if r["json_mode"]), ""),
            "tp_recall_det": round(100 * tp_dfire / tp_dn, 1) if tp_dn else None,
            "tp_det": f"{tp_dfire}/{tp_dn}",
            "fp_rate_det": round(100 * fp_dfire / fp_dn, 1) if fp_dn else None,
            "fp_det": f"{fp_dfire}/{fp_dn}",
            "tp_recall_evt": round(100 * tp_fire / tp_n, 1) if tp_n else None,
            "tp_evt": f"{tp_fire}/{tp_n}",
            "fp_rate_evt": round(100 * fp_fire / fp_n, 1) if fp_n else None,
            "fp_evt": f"{fp_fire}/{fp_n}",
            "baseline_fire_rate": round(100 * bl_fire / bl_n, 1) if bl_n else None,
            "baseline": f"{bl_fire}/{bl_n}",
            "cost_per_event_usd": round(sum(costs) / len(costs), 6) if costs else None,
            "total_cost_usd": round(sum(costs), 4),
            "latency_p50_ms": lats[len(lats) // 2] if lats else None,
        }
    SUMMARY_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="current",
                    help="lista: 'current' ou '<alias>:<perfil>' (ex.: gemma-3-27b:casc_v1)")
    ap.add_argument("--limit", type=int, default=None, help="N eventos por categoria")
    ap.add_argument("--cats", default=None, help="tp,fp,indefinido,baseline")
    ap.add_argument("--workers", type=int, default=3,
                    help="open-weight on-demand tem TPM baixo; 3 é o default seguro")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--aggregate-only", action="store_true")
    ap.add_argument("--skip-review-gate", action="store_true",
                    help="APENAS p/ smoke: ignora pendências da Fase 0")
    ap.add_argument("--tag", default=None)
    a = ap.parse_args()

    global CSV_PATH, SUMMARY_PATH
    if a.tag:
        CSV_PATH = RESULTS / f"bench_bedrock_{a.tag}.csv"
        SUMMARY_PATH = RESULTS / f"bench_bedrock_{a.tag}_summary.json"
    if a.aggregate_only:
        aggregate()
        return

    excluded = load_review(strict=not (a.skip_review_gate or a.dry_run))
    specs = {n: resolve_arm(n) for n in a.arms.split(",") if n.strip()}
    if any(s["provider"] == "gemini" for s in specs.values()) and not _TEST_KEY:
        raise SystemExit("braço de controle Gemini exige GEMINI_TEST_API_KEY no ambiente")

    cats = a.cats.split(",") if a.cats else None
    events = load_events(a.limit, cats, excluded)
    done = set() if a.dry_run else done_keys()
    jobs = [(ev, n) for n in specs for ev in events if (n, ev["event_id"]) not in done]
    print(f"arms={list(specs)} eventos={len(events)} (excluídos na Fase 0: {len(excluded)}) "
          f"jobs={len(jobs)} dry={a.dry_run}")

    if a.dry_run:
        import statistics
        recs = [run_one(ev, n, specs[n], True) for ev, n in jobs]
        for n in specs:
            sub = [r for r in recs if r["arm"] == n]
            if not sub:
                continue
            wins = [r["n_window"] for r in sub]
            print(f"  [{n}] janela med={int(statistics.median(wins))} "
                  f"min={min(wins)} max={max(wins)} | gate={sub[0]['gate_conf']} frames | "
                  f"detail: {int(statistics.median(r['n_images_sent'] for r in sub))} img med, "
                  f"{statistics.median(r['payload_mb'] for r in sub):.2f}MB med, "
                  f"{sum(1 for r in sub if r['n_dropped_payload'])} eventos com corte de payload")
        return

    total, done_n = len(jobs), 0
    for n, spec in specs.items():
        arm_jobs = [ev for ev, n2 in jobs if n2 == n]
        if not arm_jobs:
            continue
        print(f"=== {n}: provider={spec['provider']} prompt={spec.get('prompt')} "
              f"stages={spec.get('stages', 2)} img={spec.get('img', '-')} "
              f"({len(arm_jobs)} eventos) ===")
        buf = []
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futs = [pool.submit(run_one, ev, n, spec, False) for ev in arm_jobs]
            for fut in as_completed(futs):
                r = fut.result()
                done_n += 1
                buf.append(r)
                tag = "ERR" if r["error"] else f"gate={r['gate_fire']} disp={r['disposal']}"
                print(f"  [{done_n}/{total}] {r['arm']} {r['category']} {r['event_id']} "
                      f"{tag} {r['error'][:70]}")
                if len(buf) >= 5:
                    append_csv(buf)
                    buf = []
        if buf:
            append_csv(buf)
    aggregate()


if __name__ == "__main__":
    main()
