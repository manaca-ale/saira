#!/usr/bin/env python3
"""Campanha 25: testa pile_volume_change ISOLADO com crops hi-res (esp32_002).

Hipótese (do usuário): as camps 11-14 testaram pile_volume_change SEM crops
hi-res. Talvez com o close da pile-zone o modelo consiga medir o delta de
volume de forma confiável e isso sozinho separe CON de REJ.

Design — "pile-only puro":
- Envia SÓ os N crops hi-res da pile_zone (upscale 2x), em ordem cronológica.
  NÃO envia frames globais, NÃO pede raciocínio de pessoa/anti-padrões.
- Prompt minimalista: o modelo olha SÓ a pilha e responde:
    pile_volume_change ∈ {increased, decreased, unchanged}
    pile_delta_confidence 0-100
    short reason
- Decisão derivada: pred = CON sse pile_volume_change == "increased", senão REJ.
- Mede acc/recall/spec contra ground-truth (status DB) em TODOS cam_11 events.

Isola o poder discriminativo CRU do delta-de-pilha-via-VLM-com-crop.

Reusa _bench_common.py (fetch_events, load_event, resolve_frame, sample_n) e a
mesma lógica de crop da camp 24.

Vertex AI:
  GOOGLE_GENAI_USE_VERTEXAI=true
  GOOGLE_APPLICATION_CREDENTIALS=/tmp/saira-bench-vertex.json
  GOOGLE_CLOUD_PROJECT=gen-lang-client-0841492152
  GOOGLE_CLOUD_LOCATION=global
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import cv2
import psycopg2

sys.path.insert(0, str(Path(__file__).parent))

from _bench_common import (  # noqa: E402
    DEVICE_BY_CAM, fetch_events, load_event, resolve_frame, sample_n,
)
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
FLASH_IN_PRICE = 0.30 / 1e6
FLASH_OUT_PRICE = 2.50 / 1e6
N_CROP_FRAMES = 12        # crops sent (uniform over the cascade window)
CROP_UPSCALE = 2          # match prod GEMINI_GATE_PILECROP_UPSCALE
TMP = Path("/tmp/flash_per_camera")
TMP.mkdir(parents=True, exist_ok=True)

CACHE_PATH = Path("/tmp/pile_volume_delta_cache.json")
RESULTS_PATH = Path("/tmp/pile_volume_delta_results.json")

SYSTEM_PROMPT = """
Voce e um medidor visual de VOLUME de uma pilha de lixo num ponto fixo de
Mangabeira, Recife. Voce recebe SOMENTE recortes (crops) em alta resolucao da
MESMA regiao (a pile-zone), em ordem cronologica (primeiro = mais antigo,
ultimo = mais recente), de uma janela de poucos minutos.

Sua UNICA tarefa: comparar o VOLUME de material acumulado na pilha entre o
PRIMEIRO e o ULTIMO crop e classificar a mudanca. NAO julgue comportamento de
pessoas. NAO decida sobre infracao. Apenas meca a pilha.

Definicoes:
- "increased": ha MAIS material/sacos/objetos na pilha no ultimo crop do que no
  primeiro (apareceu material novo que permaneceu). Pessoas apenas passando NAO
  contam — so conta material que FICOU na pilha.
- "decreased": ha MENOS material no ultimo crop (pilha foi parcial/totalmente
  removida — coleta/limpeza).
- "unchanged": o volume da pilha esta essencialmente igual entre primeiro e
  ultimo crop (variacoes de sombra/iluminacao/pessoa passando NAO sao mudanca).

ATENCAO: a pilha pre-existente e GRANDE e esta SEMPRE presente. A presenca de
sacos NAO significa "increased" — so e "increased" se houver material NOVO que
nao estava no primeiro crop e permanece no ultimo. Em duvida, "unchanged".

Responda APENAS JSON valido:
{
  "pile_volume_change": "increased" | "decreased" | "unchanged",
  "pile_delta_confidence": <int 0-100>,
  "reason": "<= 200 chars, o que mudou concretamente entre primeiro e ultimo crop>"
}
""".strip()


if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() == "true":
    CLIENT = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
    )
    PROVIDER = "vertex"
else:
    CLIENT = genai.Client(api_key=os.environ["GEMINI_TEST_API_KEY"])
    PROVIDER = "ai_studio"


def pile_bbox(polygon):
    try:
        pts = [pt for poly in polygon for pt in poly]
        xs = [int(p[0]) for p in pts]
        ys = [int(p[1]) for p in pts]
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)
    except Exception:
        return None


def fetch_pile_bbox(camera_id: int):
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("SELECT pile_zone_polygon FROM cameras WHERE id = %s", (camera_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row or not row[0]:
        return None
    return pile_bbox(row[0])


def crop_pile(img_path: Path, bbox, upscale: int = 2):
    img = cv2.imread(str(img_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    x0, y0, x1, y1 = bbox
    cx0, cy0 = max(0, min(x0, w - 1)), max(0, min(y0, h - 1))
    cx1, cy1 = max(cx0 + 1, min(x1, w)), max(cy0 + 1, min(y1, h))
    crop = img[cy0:cy1, cx0:cx1]
    if crop.size == 0:
        return None
    if upscale != 1:
        crop = cv2.resize(
            crop, (crop.shape[1] * upscale, crop.shape[0] * upscale),
            interpolation=cv2.INTER_LANCZOS4,
        )
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return None
    return buf.tobytes()


def build_intro(crop_names):
    return (
        f"Voce recebe {len(crop_names)} crops hi-res da pile-zone em ordem "
        f"cronologica (primeiro=earliest, ultimo=latest).\n"
        f"Crop frame names: {', '.join(crop_names)}\n\n"
        "Compare o volume da pilha entre o primeiro e o ultimo crop. "
        "Retorne APENAS JSON conforme o schema."
    )


def call_pile_delta(crop_payloads):
    parts = [types.Part.from_text(text=build_intro([n for n, _ in crop_payloads]))]
    for _, jpg in crop_payloads:
        parts.append(types.Part.from_bytes(data=jpg, mime_type="image/jpeg"))
    t0 = time.monotonic()
    resp = CLIENT.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts, role="user")],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )
    latency = int((time.monotonic() - t0) * 1000)
    u = resp.usage_metadata
    in_tok = u.prompt_token_count or 0
    out_tok = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
    try:
        obj = json.loads(resp.text)
    except Exception:
        obj = {"raw": (resp.text or "")[:400]}
    return obj, in_tok, out_tok, latency


def score(results):
    """pred=CON sse pile_volume_change == 'increased'."""
    n = len(results)
    tp = sum(1 for r in results if r["pred"] == "CON" and r["gt"] == "CON")
    tn = sum(1 for r in results if r["pred"] == "REJ" and r["gt"] == "REJ")
    fp = sum(1 for r in results if r["pred"] == "CON" and r["gt"] == "REJ")
    fn = sum(1 for r in results if r["pred"] == "REJ" and r["gt"] == "CON")
    return {"n": n, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "acc": (tp + tn) / max(n, 1),
            "precision": tp / max(tp + fp, 1),
            "recall": tp / max(tp + fn, 1),
            "specificity": tn / max(tn + fp, 1)}


def main():
    bbox = fetch_pile_bbox(11)
    if bbox is None:
        print("ERROR: no pile_zone_polygon for cam_11", flush=True)
        return 2
    print(f"[bbox] esp32_002 pile_zone bbox={bbox} "
          f"(w={bbox[2]-bbox[0]}, h={bbox[3]-bbox[1]})", flush=True)

    events = [e for e in fetch_events() if e["cam"] == 11]
    print(f"[fetch] {len(events)} cam_11 events  test=PILE_VOLUME_DELTA "
          f"provider={PROVIDER}", flush=True)
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    print(f"[cache] {len(cache)} already done", flush=True)

    results = []
    total_in = total_out = 0
    cost = 0.0
    smoke_only = os.environ.get("SMOKE_ONLY") == "1"

    for i, ev in enumerate(events, 1):
        device_id = DEVICE_BY_CAM.get(ev["cam"])
        det = load_event(ev["id"])
        if not det or not det.get("frames"):
            continue
        if ev["id"] in cache:
            row = cache[ev["id"]]
            results.append(row)
            total_in += row.get("in_tok", 0)
            total_out += row.get("out_tok", 0)
            cost += row.get("cost_usd", 0)
            continue

        frames = det["frames"]
        c_idxs = sample_n(frames, N_CROP_FRAMES)
        crop_payloads = []
        for k in c_idxs:
            f = frames[k]
            p = resolve_frame(TMP, f["image_url"], f["frame_name"], device_id)
            if not p:
                continue
            jpg = crop_pile(p, bbox, upscale=CROP_UPSCALE)
            if jpg is not None:
                crop_payloads.append((f["frame_name"], jpg))
        if len(crop_payloads) < 4:
            print(f"  {ev['id'][:8]}: only {len(crop_payloads)} crops, skip",
                  flush=True)
            continue

        try:
            obj, in_tok, out_tok, latency = call_pile_delta(crop_payloads)
        except Exception as exc:
            print(f"  {ev['id'][:8]} ERROR: {exc}", flush=True)
            continue

        ev_cost = in_tok * FLASH_IN_PRICE + out_tok * FLASH_OUT_PRICE
        total_in += in_tok
        total_out += out_tok
        cost += ev_cost
        gt = "CON" if ev["status"] == "CONFIRMADO" else "REJ"
        pvc = (obj.get("pile_volume_change") or "").lower()
        pred = "CON" if pvc == "increased" else "REJ"
        row = {
            "id": ev["id"], "ts": ev["ts"], "cam": ev["cam"], "gt": gt,
            "pred": pred, "pile_volume_change": pvc,
            "pile_delta_confidence": obj.get("pile_delta_confidence"),
            "reason": (obj.get("reason") or "")[:300],
            "in_tok": in_tok, "out_tok": out_tok, "latency_ms": latency,
            "cost_usd": round(ev_cost, 6), "n_crops": len(crop_payloads),
        }
        results.append(row)
        cache[ev["id"]] = row
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

        mark = "OK" if pred == gt else "MISS"
        print(f"  {i:>2}/{len(events)} {ev['ts'][:16]} gt={gt} "
              f"pvc={pvc:>9} pred={pred} conf={obj.get('pile_delta_confidence')} "
              f"{mark} ({latency}ms ${ev_cost:.4f} c={len(crop_payloads)})",
              flush=True)
        if smoke_only:
            print("\nSMOKE_ONLY=1 — parando apos 1 evento.")
            break

    s = score(results)
    print()
    print(f"=== PILE_VOLUME_DELTA (crops-only) — n={s['n']} (cam_11) ===")
    print(f"Regra: pred=CON sse pile_volume_change=='increased'")
    print(f"acc={s['acc']:.2%}  TP={s['tp']} TN={s['tn']} FP={s['fp']} FN={s['fn']}")
    print(f"precision={s['precision']:.2%}  recall={s['recall']:.2%}  "
          f"specificity={s['specificity']:.2%}")
    # distribution of pile_volume_change by ground truth
    from collections import Counter
    for g in ("CON", "REJ"):
        dist = Counter(r["pile_volume_change"] for r in results if r["gt"] == g)
        print(f"  gt={g}: {dict(dist)}")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} "
          f"(avg ${cost / max(s['n'], 1):.4f}/event)")

    RESULTS_PATH.write_text(json.dumps({
        "test": "pile_volume_delta_crops_only", "model": MODEL,
        "provider": PROVIDER, "pile_bbox": list(bbox),
        "score": s, "results": results, "cost_usd": round(cost, 6),
    }, ensure_ascii=False, indent=2))
    print(f"\nsaved: {RESULTS_PATH}")


if __name__ == "__main__":
    sys.exit(main() or 0)
