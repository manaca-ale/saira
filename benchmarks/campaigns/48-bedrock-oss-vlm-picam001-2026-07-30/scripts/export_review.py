#!/usr/bin/env python3
"""Camp 48 — Fase 0: exporta a janela de cada evento para revisão humana.

Antes de gastar API em 8 modelos x 122 eventos, o operador precisa ver EXATAMENTE
quais frames chegam a cada estágio e decidir se o evento é válido. Este script
constrói a janela com o MESMO código de produção que o runner usa
(`event_windows.subsample_frames` -> `fit_frames_to_payload`, mids por
`main.py:1452-1466`), então o que aparece na tela é bit-a-bit o que o modelo recebe.

Saída (fora do git, no diretório de dados):

    <official>/cam_picam001/_review_camp48/
      INDEX.csv                       <- preencher VALID (y/n) e NOTE
      por_evento/<cat>/<event_id>/
        gate/    01_first_… 02_mid1_… 03_mid2_… 04_mid3_… 05_last_….jpg
        detail/  NN[_G]_<nome>.jpg    (NN = ordem na janela; _G = também no gate)
        contact_gate.jpg              5 frames em linha, rotulados
        contact_detail.jpg            grade da janela; frames do gate em vermelho
        info.json
      por_estagio/{gate,detail}/<cat>_<event_id>_NN.jpg

Uso:
    python scripts/export_review.py                 # todos os 122 eventos
    python scripts/export_review.py --limit 3       # 3 por categoria (smoke)
    python scripts/export_review.py --verify        # confere consistência, não escreve
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "data" / "datasets" / "official"
CAM = OFFICIAL / "cam_picam001"
REVIEW = CAM / "_review_camp48"

# ── PROD-exact window env, ANTES de importar worker.config ───────────────────
# Mesmos valores pinados pelo runner do camp 47 (bench_picam.py:65-79), que por
# sua vez vieram de `docker inspect saira-yolo-worker-prod` em 22/07.
os.environ["GEMINI_CASCADE_MAX_FRAMES"] = "48"
os.environ["GEMINI_MAX_PAYLOAD_BYTES"] = "8000000"
os.environ["GEMINI_GATE_MID_FRAMES"] = "3"
os.environ["GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE"] = "85"
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")

sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.config as cfg                     # noqa: E402
import worker.event_windows as event_windows    # noqa: E402

CATS = ("tp", "fp", "indefinido", "baseline")


# ── janela: idêntica ao runner (bench_picam.py:395-409) ──────────────────────
def build_window(frames):
    win = event_windows.subsample_frames(frames, cfg.GEMINI_CASCADE_MAX_FRAMES)
    win = event_windows.fit_frames_to_payload(win, cfg.GEMINI_MAX_PAYLOAD_BYTES)
    return win


def gate_mids(win):
    n = len(win)
    mid_count = max(0, cfg.GEMINI_GATE_MID_FRAMES)
    if n < 3 or mid_count == 0:
        return None
    step = (n - 1) / (mid_count + 1)
    ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
    ks = [k for k in ks if 0 < k < n - 1]
    return [win[k] for k in ks] or None


def gate_frames(win):
    """Os frames que o gate recebe, na ordem em que analyze_new_litter_with_gemini
    os envia: first, mids…, last. Retorna [(rótulo, Path, índice_na_janela)]."""
    mids = gate_mids(win) or []
    out = [("first", win[0], 0)]
    for i, m in enumerate(mids, start=1):
        out.append((f"mid{i}", m, win.index(m)))
    out.append(("last", win[-1], len(win) - 1))
    return out


def load_events(limit=None):
    rows = []
    for cat in CATS:
        for lab in sorted((CAM / cat).glob("*/label.json")):
            L = json.loads(lab.read_text(encoding="utf-8"))
            frames = sorted((lab.parent / "frames").glob("*.jpg"))
            if len(frames) < 2:
                continue
            rows.append({"event_id": L["event_id"], "category": cat, "frames": frames,
                         "datetime": L.get("datetime", ""), "label": L,
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


# ── escrita ─────────────────────────────────────────────────────────────────
def link_or_copy(src: Path, dst: Path):
    """Hardlink (mesmo volume D:) para não duplicar ~900 MB; cópia se falhar."""
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def contact_sheet(paths, out: Path, cols, thumb_w, labels, highlight=()):
    """Grade de miniaturas rotuladas. `highlight` = índices com moldura vermelha."""
    from PIL import Image, ImageDraw

    if not paths:
        return
    bar = 18
    with Image.open(paths[0]) as im0:
        ar = im0.height / im0.width
    tw, th = thumb_w, int(thumb_w * ar)
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + bar)), (28, 28, 30))
    draw = ImageDraw.Draw(sheet)
    for i, p in enumerate(paths):
        x, y = (i % cols) * tw, (i // cols) * (th + bar)
        with Image.open(p) as im:
            sheet.paste(im.convert("RGB").resize((tw, th)), (x, y + bar))
        if i in highlight:
            draw.rectangle([x + 1, y + bar + 1, x + tw - 2, y + bar + th - 2],
                           outline=(255, 40, 40), width=3)
        draw.text((x + 3, y + 3), labels[i][:34], fill=(235, 235, 235))
    sheet.save(out, "JPEG", quality=82)


def export_one(ev, write=True):
    frames = ev["frames"]
    win = build_window(frames)
    gates = gate_frames(win)
    gate_idxs = {idx for _, _, idx in gates}
    L = ev["label"]

    # subsample_frames corta por CONTAGEM (48); fit_frames_to_payload corta por BYTES.
    # Separar os dois é o que revela se a janela vista pelo modelo difere do evento.
    n_sub = len(event_windows.subsample_frames(frames, cfg.GEMINI_CASCADE_MAX_FRAMES))
    info = {
        "event_id": ev["event_id"], "category": ev["category"], "det_id": ev["det_id"],
        "datetime": ev["datetime"], "coalesced": L.get("coalesced", False),
        "n_raw": len(frames), "n_after_subsample": n_sub, "n_window": len(win),
        "n_dropped_subsample": len(frames) - n_sub,
        "n_dropped_payload": n_sub - len(win),
        "window_bytes": sum(p.stat().st_size for p in win),
        "gate_window_idxs": sorted(gate_idxs),
        "gate_frames": [p.name for _, p, _ in gates],
        "detail_frames": [p.name for p in win],
        "classificacao": L.get("classificacao", ""),
        "justificativa": L.get("justificativa", ""),
        "agent1_confidence": L.get("agent1_confidence", ""),
        "tipo_residuo": L.get("tipo_residuo", ""),
        "volumetria": L.get("volumetria", ""),
        "selected_frame_name": L.get("selected_frame_name", ""),
        "evidence_summary_PROD": L.get("evidence_summary", ""),
    }
    if not write:
        return info

    ev_dir = REVIEW / "por_evento" / ev["category"] / ev["event_id"]
    g_dir, d_dir = ev_dir / "gate", ev_dir / "detail"
    for d in (g_dir, d_dir):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    flat_g = REVIEW / "por_estagio" / "gate"
    flat_d = REVIEW / "por_estagio" / "detail"
    flat_g.mkdir(parents=True, exist_ok=True)
    flat_d.mkdir(parents=True, exist_ok=True)

    tag = f"{ev['category']}_{ev['event_id']}"
    for i, (role, p, idx) in enumerate(gates, start=1):
        name = f"{i:02d}_{role}_w{idx:03d}_{p.name}"
        link_or_copy(p, g_dir / name)
        link_or_copy(p, flat_g / f"{tag}_{name}")
    for i, p in enumerate(win):
        mark = "_G" if i in gate_idxs else ""
        name = f"{i:03d}{mark}_{p.name}"
        link_or_copy(p, d_dir / name)
        link_or_copy(p, flat_d / f"{tag}_{name}")

    contact_sheet([p for _, p, _ in gates], ev_dir / "contact_gate.jpg",
                  cols=len(gates), thumb_w=420,
                  labels=[f"{i:02d} {r} (w{idx})" for i, (r, _, idx) in enumerate(gates, 1)])
    contact_sheet(win, ev_dir / "contact_detail.jpg",
                  cols=min(8, max(4, len(win))), thumb_w=240,
                  labels=[f"{i:03d}{' GATE' if i in gate_idxs else ''}" for i in range(len(win))],
                  highlight=gate_idxs)
    (ev_dir / "info.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


INDEX_COLS = ["VALID", "NOTE", "event_id", "category", "classificacao", "det_id",
              "coalesced", "n_raw", "n_window", "n_dropped_subsample",
              "n_dropped_payload", "datetime", "agent1_confidence", "tipo_residuo",
              "justificativa"]


def write_index(infos):
    """INDEX.csv com VALID/NOTE primeiro (colunas de edição à esquerda).
    Preserva o que o operador já preencheu, se o arquivo existir."""
    prev = {}
    idx_path = REVIEW / "INDEX.csv"
    if idx_path.exists():
        with idx_path.open(encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                prev[r["event_id"]] = (r.get("VALID", ""), r.get("NOTE", ""))
    with idx_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=INDEX_COLS)
        w.writeheader()
        for info in infos:
            v, n = prev.get(info["event_id"], ("", ""))
            w.writerow({"VALID": v, "NOTE": n,
                        **{k: info.get(k, "") for k in INDEX_COLS[2:]}})
    return idx_path, sum(1 for v, _ in prev.values() if v)


def verify(infos):
    """Consistência entre o que exportei e a janela recomputada + invariantes."""
    bad = []
    for info in infos:
        ev_dir = REVIEW / "por_evento" / info["category"] / info["event_id"]
        g = sorted((ev_dir / "gate").glob("*.jpg"))
        d = sorted((ev_dir / "detail").glob("*.jpg"))
        n_g_expected = len(info["gate_frames"])
        if len(g) != n_g_expected:
            bad.append(f"{info['event_id']}: gate tem {len(g)} arquivos, esperado {n_g_expected}")
        if len(d) != info["n_window"]:
            bad.append(f"{info['event_id']}: detail tem {len(d)} arquivos, esperado {info['n_window']}")
        # os frames marcados _G no detail devem ser exatamente os do gate
        marked = {p.name.split("_G_", 1)[1] for p in d if "_G_" in p.name}
        if marked != set(info["gate_frames"]):
            bad.append(f"{info['event_id']}: marcas _G {sorted(marked)} != gate {sorted(info['gate_frames'])}")
        # o gate é subconjunto ordenado da janela, com first e last nas pontas
        if info["gate_frames"][0] != info["detail_frames"][0]:
            bad.append(f"{info['event_id']}: gate[0] != janela[0]")
        if info["gate_frames"][-1] != info["detail_frames"][-1]:
            bad.append(f"{info['event_id']}: gate[-1] != janela[-1]")
        if info["window_bytes"] > cfg.GEMINI_MAX_PAYLOAD_BYTES:
            bad.append(f"{info['event_id']}: janela {info['window_bytes']}B > teto")
        if not (ev_dir / "contact_detail.jpg").exists():
            bad.append(f"{info['event_id']}: contact_detail.jpg ausente")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="N eventos por categoria (smoke)")
    ap.add_argument("--verify", action="store_true", help="só conferir, não escrever")
    args = ap.parse_args()

    evs = load_events(args.limit)
    print(f"eventos: {len(evs)}  (max_frames={cfg.GEMINI_CASCADE_MAX_FRAMES}, "
          f"payload={cfg.GEMINI_MAX_PAYLOAD_BYTES}, mids={cfg.GEMINI_GATE_MID_FRAMES})")

    infos = []
    for i, ev in enumerate(evs, 1):
        infos.append(export_one(ev, write=not args.verify))
        if i % 20 == 0 or i == len(evs):
            print(f"  {i}/{len(evs)}")

    if args.verify:
        problems = verify(infos)
        print("\n".join(problems) if problems else "verify OK")
        return 1 if problems else 0

    idx_path, n_prev = write_index(infos)
    by_cat = {}
    for info in infos:
        c = by_cat.setdefault(info["category"], {"n": 0, "drop_sub": 0, "drop_pay": 0})
        c["n"] += 1
        c["drop_sub"] += info["n_dropped_subsample"]
        c["drop_pay"] += info["n_dropped_payload"]
    print("\ncategoria   eventos  frames cortados p/ contagem  p/ payload")
    for cat in CATS:
        if cat in by_cat:
            c = by_cat[cat]
            print(f"  {cat:11} {c['n']:4}   {c['drop_sub']:20}   {c['drop_pay']:10}")
    print(f"\nrevisão em: {REVIEW}")
    print(f"INDEX.csv:  {idx_path}  ({n_prev} veredictos preservados)")
    print("Preencha VALID (y/n) e NOTE. O runner da Fase B recusa rodar com pendências.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
