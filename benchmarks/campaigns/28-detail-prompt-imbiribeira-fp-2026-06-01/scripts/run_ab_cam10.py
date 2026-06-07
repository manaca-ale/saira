#!/usr/bin/env python3
"""Camp 28 — A/B detail prompt cam_10 Imbiribeira: V1 baseline vs V1_IMBIRIBEIRA.

Roda DENTRO do worker (saira-yolo-worker-prod): _bench_common (frames locais),
fetch_events (DB), chave de TESTE GEMINI_TEST_API_KEY (projeto gen-lang-client-0841492152).

Braço A (V1): SYS_V1_PROD (V1 atual de prod + bloco de schema do bench).
Braço B (V1_IMBIRIBEIRA): SYS_V1_PROD com o bloco de direção EMLURB/coleta + proteção
de recall veicular inserido ANTES do schema. Diferença controlada = só minhas adições.

Paridade prod: Flash 2.5, temp 0, N_FRAMES=48, mesmo pipeline de frames.
Só cam_10 (camera_id=10). Cache por (arm,id). Saída: results-<arm>.json.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bench_common import (  # noqa: E402
    DEVICE_BY_CAM, build_intro, fetch_events, jpeg_bytes,
    load_event, resolve_frame, sample_n,
)
from _baseline_prompts import SYS_V1_PROD  # noqa: E402
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"
FLASH_IN_PRICE = 0.30 / 1e6
FLASH_OUT_PRICE = 2.50 / 1e6
N_FRAMES = 48
CAM_ID = 10
TMP = Path("/tmp/camp28_frames")
TMP.mkdir(parents=True, exist_ok=True)
OUT_DIR = Path("/tmp/camp28")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Bloco candidato (inserido antes do schema, recall-protetor) ----
IMBIRIBEIRA_BLOCK = """
DISCRIMINADOR DE DIRECAO DO MATERIAL (decisivo para esta camera):
Imbiribeira tem coleta municipal e catadores frequentes. Antes de confirmar,
verifique PARA ONDE o material vai:
- Material indo DO veiculo/pessoa PARA o chao (pilha CRESCE) = DESCARTE.
- Material indo DO chao PARA o veiculo/carroca (pilha DIMINUI) = COLETA, NAO descarte.

ATIVIDADES QUE NAO SAO DESCARTE (infraction_confirmed=false):
- Coleta EMLURB: caminhao COMPACTADOR (carroceria FECHADA, hopper traseiro)
  parado, pessoas levando sacos/restos DO CHAO PARA o caminhao. A pilha DIMINUI
  ou some entre os frames.
- Catador/carroceiro COLETANDO: pessoa com carroca de madeira levando reciclaveis
  (papelao, plastico, metal) DO CHAO PARA a carroca. Pilha diminui.
- Transeuntes/transito misto: pessoas, carros, motos, ciclistas em POSICOES
  MUITO DIFERENTES entre frames, sem ninguem ESTACIONARIO junto a pilha.

PROTECAO DE RECALL (esta camera tem descarte veicular real e frequente):
- Caminhonete/pickup/mini-caminhao com CARROCERIA ABERTA descarregando = DESCARTE,
  mesmo sem ver o material no ar. Carroceria aberta + pessoa estacionaria atras
  do veiculo = DESCARTE.
- Se a direcao do material for AMBIGUA mas houver pessoa ESTACIONARIA junto a
  pilha manuseando material por 2+ frames, classifique como DESCARTE (na duvida,
  confirme — o custo de perder um descarte real e maior).
- So rejeite por COLETA quando ela for CLARA: caminhao compactador fechado, OU
  pilha visivelmente DIMINUINDO, OU carroca recebendo material do chao.
"""

_SCHEMA_MARKER = "Schema do JSON de resposta:"
if _SCHEMA_MARKER in SYS_V1_PROD:
    _head, _schema = SYS_V1_PROD.split(_SCHEMA_MARKER, 1)
    SYS_V1_IMBIRIBEIRA = _head.rstrip() + "\n" + IMBIRIBEIRA_BLOCK + "\n" + _SCHEMA_MARKER + _schema
else:
    SYS_V1_IMBIRIBEIRA = SYS_V1_PROD.rstrip() + "\n" + IMBIRIBEIRA_BLOCK

ARMS = {"V1": SYS_V1_PROD, "V1_IMBIRIBEIRA": SYS_V1_IMBIRIBEIRA}

BENCH_KEY = os.environ["GEMINI_TEST_API_KEY"]
CLIENT = genai.Client(api_key=BENCH_KEY)
print("[init] backend=AI Studio (test project)", flush=True)


def call(system_prompt, paths, frame_names, cam_id):
    intro = build_intro(paths, frame_names, cam_id)
    parts = [types.Part.from_text(text=intro)]
    for p in paths:
        parts.append(types.Part.from_bytes(data=jpeg_bytes(p), mime_type="image/jpeg"))
    t0 = time.monotonic()
    resp = CLIENT.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts, role="user")],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
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


def main():
    events = [e for e in fetch_events() if e["cam"] == CAM_ID]
    print(f"[fetch] {len(events)} cam_{CAM_ID} events", flush=True)

    for arm, sysprompt in ARMS.items():
        cache_path = OUT_DIR / f"cache-{arm}.json"
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        results = []
        total_in = total_out = 0
        cost = 0.0
        device_id = DEVICE_BY_CAM[CAM_ID]
        for i, ev in enumerate(events, 1):
            det = load_event(ev["id"])
            if not det or not det.get("frames"):
                continue
            if ev["id"] in cache:
                row = cache[ev["id"]]
            else:
                frames = det["frames"]
                idxs = sample_n(frames, N_FRAMES)
                paths, names = [], []
                for k in idxs:
                    f = frames[k]
                    p = resolve_frame(TMP, f["image_url"], f["frame_name"], device_id)
                    if p:
                        paths.append(p); names.append(f["frame_name"])
                if len(paths) < 4:
                    print(f"  {ev['id'][:8]}: only {len(paths)} frames", flush=True)
                    continue
                try:
                    obj, in_tok, out_tok, latency = call(sysprompt, paths, names, CAM_ID)
                except Exception as exc:
                    print(f"  {ev['id'][:8]} [{arm}] ERROR: {exc}", flush=True)
                    continue
                ev_cost = in_tok * FLASH_IN_PRICE + out_tok * FLASH_OUT_PRICE
                gt = "CON" if ev["status"] == "CONFIRMADO" else "REJ"
                pred = "CON" if obj.get("infraction_confirmed") else "REJ"
                row = {"id": ev["id"], "ts": ev["ts"], "gt": gt, "pred": pred,
                       "confidence": obj.get("confidence_0_100"),
                       "evidence_summary": (obj.get("evidence_summary") or "")[:200],
                       "arm": arm, "in_tok": in_tok, "out_tok": out_tok,
                       "latency_ms": latency, "cost_usd": round(ev_cost, 6),
                       "n_frames_used": len(paths)}
                cache[ev["id"]] = row
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
            results.append(row)
            total_in += row["in_tok"]; total_out += row["out_tok"]; cost += row["cost_usd"]
            mark = "OK" if row["pred"] == row["gt"] else "MISS"
            print(f"  {i:>2}/{len(events)} {row['ts'][:16]} [{arm}] gt={row['gt']} "
                  f"pred={row['pred']} {mark} (${row['cost_usd']:.4f})", flush=True)

        out = OUT_DIR / f"results-{arm}.json"
        out.write_text(json.dumps({"model": MODEL, "arm": arm, "results": results,
                                   "cost_usd": round(cost, 6)},
                                  ensure_ascii=False, indent=2))
        # quick confusion
        tp = sum(1 for r in results if r["gt"] == "CON" and r["pred"] == "CON")
        fn = sum(1 for r in results if r["gt"] == "CON" and r["pred"] == "REJ")
        fp = sum(1 for r in results if r["gt"] == "REJ" and r["pred"] == "CON")
        tn = sum(1 for r in results if r["gt"] == "REJ" and r["pred"] == "REJ")
        rec = tp / max(tp + fn, 1); fpr = fp / max(fp + tn, 1)
        print(f"[{arm}] n={len(results)} TP={tp} FN={fn} FP={fp} TN={tn} "
              f"recall={rec:.0%} fp_rate={fpr:.0%} cost=${cost:.4f}", flush=True)
        print(f"saved {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
