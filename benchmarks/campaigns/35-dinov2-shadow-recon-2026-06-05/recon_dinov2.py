#!/usr/bin/env python3
"""Camp 35 — retroactive eval of the DINOv2 shadow filter on esp32_001 (Imbiribeira).

Shadow decisions are only written to the worker's stdout, which is wiped on each
container recreate — so the ~4-day shadow track record (since 2026-06-01) is lost
except for 1 surviving log line. This reconstructs it: re-runs the *persisted*
classifier (prod's own detector_dinov2.evaluate) on each esp32_001 detection since
2026-06-01, using the detection's representative frame, and cross-references the
operator's final label.

RUNS INSIDE the prod worker container (has torch + cached DINOv2 + the classifier).
Approximation vs live: live shadow scores the last N=3 cascade-window frames; here we
only have the single representative frame (the cascade window rotated). The detection
f7f0cc93 has a live log (p_con=0.0015) → sanity-check the single-frame proxy against it.

  docker cp recon_dinov2.py saira-yolo-worker-prod:/tmp/recon_dinov2.py
  docker exec saira-yolo-worker-prod python /tmp/recon_dinov2.py
"""
from __future__ import annotations

import json
import ssl
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, "/app/src")

from worker import config, detector_dinov2  # noqa: E402

DEVICE = "esp32_001"
PILE_POLYGON = [[[832, 319], [984, 334], [995, 412], [841, 410]],
                [[490, 297], [661, 311], [668, 423], [461, 427]],
                [[6, 368], [9, 476], [333, 465], [330, 343]],
                [[8, 525], [669, 508], [671, 719], [11, 715]]]

# (id8, datetime, operator_status, representative image_url)
DETECTIONS = [
    ("6deb0722", "06-01 07:38", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_07-38-23.jpg"),
    ("623d5772", "06-01 08:13", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_08-13-34.jpg"),
    ("d3c93c6c", "06-01 08:29", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_08-29-23.jpg"),
    ("c6ed3a96", "06-01 18:18", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_18-18-13.jpg"),
    ("bf273a55", "06-01 20:00", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_20-00-23.jpg"),
    ("872e9ad5", "06-01 21:04", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_21-04-38.jpg"),
    ("2acfec10", "06-01 22:14", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_22-14-13.jpg"),
    ("7b8b03f9", "06-01 22:27", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/01/2026-06-01_22-27-03.jpg"),
    ("9edc6c01", "06-02 11:10", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/02/2026-06-02_11-10-25.jpg"),
    ("a23fdfae", "06-02 11:38", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/02/2026-06-02_11-38-25.jpg"),
    ("cd8734a5", "06-02 12:01", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/02/2026-06-02_12-01-45.jpg"),
    ("806355e6", "06-02 13:54", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/02/2026-06-02_13-54-15.jpg"),
    ("c7ecb7df", "06-02 16:41", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/02/2026-06-02_16-41-00.jpg"),
    ("d6770e5d", "06-02 17:23", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/02/2026-06-02_17-29-50.jpg"),
    ("cc21c8fc", "06-02 22:55", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/02/2026-06-02_22-55-04.jpg"),
    ("eb1ecfa7", "06-03 07:04", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_07-04-45.jpg"),
    ("374fae67", "06-03 12:23", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_12-23-25.jpg"),
    ("2e089ea2", "06-03 16:01", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_16-01-35.jpg"),
    ("0c08d1bc", "06-03 16:49", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_16-49-40.jpg"),
    ("c9c2c83e", "06-03 19:33", "CONFIRMADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_19-33-09.jpg"),
    ("3ab5f12a", "06-03 22:24", "INDETERMINADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_22-24-09.jpg"),
    ("18771019", "06-03 23:27", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_23-27-20.jpg"),
    ("e0d0c244", "06-03 23:46", "REJEITADO", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/03/2026-06-03_23-46-49.jpg"),
    ("68b4ab07", "06-04 16:58", "PENDENTE", "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/esp32_001/2026/06/04/2026-06-04_16-58-40.jpg"),
    ("f7f0cc93", "06-05 01:17", "PENDENTE", "http://localhost:5005/uploads/esp32_001/labeled/2026/06/05/2026-06-05_01-17-35.jpg"),
]

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE


def resolve_frame(url: str) -> Path | None:
    if url.startswith("http://localhost:5005/uploads/"):
        local = "/app/uploads/" + url.split("/uploads/", 1)[1]
        return Path(local) if Path(local).exists() else None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "recon"})
        data = urllib.request.urlopen(req, timeout=20, context=_SSL).read()
        tmp = Path(tempfile.gettempdir()) / ("recon_" + url.rsplit("/", 1)[-1])
        tmp.write_bytes(data)
        return tmp
    except Exception as exc:  # noqa: BLE001
        print(f"  fetch fail {url}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    print(f"DINOv2 shadow recon | mode={config.DINOV2_FILTER_MODE} "
          f"devices={config.DINOV2_FILTER_DEVICES}", flush=True)
    results = []
    for id8, ts, status, url in DETECTIONS:
        fp = resolve_frame(url)
        if fp is None:
            results.append({"id8": id8, "ts": ts, "status": status,
                            "p_con": None, "would_reject": None, "reason": "no_frame"})
            print(f"  {ts} {id8} {status:14s} -> NO FRAME", flush=True)
            continue
        r = detector_dinov2.evaluate([fp], DEVICE, PILE_POLYGON)
        wr = bool(r.should_reject) if r.reason in ("rejected", "passed") else None
        results.append({"id8": id8, "ts": ts, "status": status,
                        "p_con": round(r.p_con, 4), "would_reject": wr, "reason": r.reason})
        tag = "WOULD-REJECT" if wr else ("pass" if wr is False else r.reason)
        print(f"  {ts} {id8} {status:14s} -> p_con={r.p_con:.4f} {tag}", flush=True)

    # Scoring vs operator labels (threshold = classifier's, p_con < thr ⇒ reject)
    def grp(st):
        return [r for r in results if r["status"] == st and r["would_reject"] is not None]
    rej = grp("REJEITADO")     # true FP — DINOv2 SHOULD reject
    con = grp("CONFIRMADO")    # true TP — DINOv2 must NOT reject
    ind = grp("INDETERMINADO")
    fp_caught = sum(r["would_reject"] for r in rej)
    tp_killed = sum(r["would_reject"] for r in con)
    summary = {
        "device": DEVICE,
        "n_total": len(results),
        "REJEITADO_FP": {"n": len(rej), "would_reject": fp_caught,
                          "fp_catch_rate": round(fp_caught / len(rej), 3) if rej else None},
        "CONFIRMADO_TP": {"n": len(con), "would_reject(false_reject)": tp_killed},
        "INDETERMINADO": {"n": len(ind), "would_reject": sum(r["would_reject"] for r in ind)},
    }
    out = Path("/tmp/recon_results.json")
    out.write_text(json.dumps({"summary": summary, "results": results},
                              ensure_ascii=False, indent=2))
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"-> {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
