#!/usr/bin/env python3
"""Camp 37e — build exact-window corpus for ALL historical cam_14 positives.

For each CONFIRMADO/INDETERMINADO detection (DB), find its audit line(s)
(window_first/last per gate decision), slice the detection_frames S3 index to the
window bounds, apply the prod 5-frame pick (0, n//4, n//2, 3n//4, n-1) and download
only those frames. Coalesced detections yield one window per triggered audit line.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(r"c:\saira")
DET_DIR = ROOT / "tmp" / "det_frames_pos"
AUDIT_DIR = ROOT / "tmp" / "audit_all"
OUT = ROOT / "tmp" / "ar_pos_s3"
sys.stdout.reconfigure(encoding="utf-8")

STATUS = {  # DB status + spreadsheet refinement
    "b797daa9": ("INDET", "indefinido: pessoa agachada"),
    "01c9e4c7": ("DESCARTE", "carroça (planilha)"),
    "6834dad7": ("DESCARTE", "carroça/carrinho grande (planilha)"),
    "01e54259": ("DESCARTE", "carroça/carrinho grande (planilha)"),
    "9085ad0e": ("CONF", ""),
    "8657dafd": ("COLETA", "planilha: coleta — NÃO é positivo"),
    "95dd7824": ("INDET", ""), "bd466bda": ("INDET", ""), "6e2e95ce": ("INDET", ""),
    "d7822b53": ("CONF", ""), "bcb8038c": ("CONF", ""), "a5a72209": ("CONF", ""),
    "6a126950": ("INDET", ""), "ce13f76c": ("CONF", ""), "9e112c6d": ("INDET", ""),
    "6328e4e6": ("CONF", ""), "4d51d0a1": ("INDET", ""), "50c32313": ("CONF", ""),
    "0c4976c0": ("INDET", ""), "f7913b02": ("INDET", ""), "0f2e9b60": ("INDET", ""),
    "0cb3394b": ("INDET", "já testado como 08_KEPT"),
}


def audit_lines_by_det() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for day_dir in sorted(AUDIT_DIR.iterdir()):
        f = day_dir / "esp32_005.jsonl"
        if not f.exists():
            continue
        for ln in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            det = r.get("detection_id")
            if det:
                out.setdefault(det[:8], []).append(r)
    return out


def pick5_idx(n: int) -> list[int]:
    if n <= 5:
        return list(range(n))
    idxs = [0, n // 4, n // 2, 3 * n // 4, n - 1]
    seen, out = set(), []
    for i in idxs:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def main() -> int:
    audits = audit_lines_by_det()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for jf in sorted(DET_DIR.glob("*.json")):
        det8 = jf.name[:8]
        status, note = STATUS.get(det8, ("?", ""))
        data = json.loads(jf.read_text(encoding="utf-8"))
        frames = sorted(data.get("frames", []), key=lambda x: x["frame_name"])
        lines = audits.get(det8, [])
        if not lines:
            print(f"{det8} {status:8} NO_AUDIT (detecção anterior a 28/05?) frames={len(frames)}")
            continue
        for k, r in enumerate(lines):
            lo, hi = r["window_first_frame"], r["window_last_frame"]
            win = [f for f in frames if lo <= f["frame_name"] <= hi]
            tag = f"{det8}_w{k}" if len(lines) > 1 else det8
            if len(win) < 5:
                print(f"{tag} {status:8} window {lo[11:19]}..{hi[11:19]} size_audit={r['window_size']} -> only {len(win)} frames in index, SKIP")
                continue
            picks = [win[i] for i in pick5_idx(len(win))]
            wd = OUT / f"{status}_{tag}_{hi[11:19].replace(':','-')}"
            wd.mkdir(exist_ok=True)
            n_ok = 0
            for p in picks:
                dest = wd / p["frame_name"]
                if dest.exists() and dest.stat().st_size > 1000:
                    n_ok += 1
                    continue
                url = p["image_url"]
                if url.startswith("/s3-images/"):
                    url = "https://saira-images.s3.sa-east-1.amazonaws.com/" + url[len("/s3-images/"):]
                if not url.startswith("http"):
                    continue
                try:
                    with urlopen(url, timeout=30) as resp:
                        b = resp.read()
                    if len(b) > 1000:
                        dest.write_bytes(b)
                        n_ok += 1
                except Exception as e:
                    print(f"   DL_FAIL {p['frame_name']}: {e}")
            print(f"{tag} {status:8} win {lo[11:19]}..{hi[11:19]} n_win={len(win)}/{r['window_size']} a1c={r['agent1_confidence']} downloaded={n_ok}/5 {note}")
            manifest.append({"dir": wd.name, "det": det8, "status": status, "a1c_prod": r["agent1_confidence"],
                             "first": lo, "last": hi, "n_win": len(win), "note": note})
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(manifest)} janelas prontas em {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
