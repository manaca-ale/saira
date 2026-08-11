#!/usr/bin/env python3
"""Gemini 2.5 Flash Lite as Agent-3 verifier — same 8 events as Pro & Sonnet.

Mirror of agent3_proto.py but with model=gemini-2.5-flash-lite.
Pricing: $0.10/M in, $0.40/M out (very cheap).
Sanity check whether Flash Lite suffices for Agent-3 or if we need Pro.
"""
from __future__ import annotations
import io
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
from google import genai
from google.genai import types
from PIL import Image

BENCH_KEY = os.environ["GEMINI_TEST_API_KEY"]
MODEL = "gemini-2.5-flash-lite"
FLASH_LITE_IN_PRICE = 0.10 / 1e6
FLASH_LITE_OUT_PRICE = 0.40 / 1e6

TEST = [
    ("E1", "9e90cc61-5d0d-4d42-b5a2-52a1e92eaa25", "REJ", "14:43 cam10"),
    ("E2", "2900d8ea-77ee-41a5-894d-1b3863801919", "REJ", "11:23 cam10"),
    ("E3", "90c05405-10a3-4d14-923b-3ce8b683eded", "REJ", "13:41 cam11"),
    ("E4", "c4224caf-6cb9-48df-846d-b7ad0ea7d141", "REJ", "13:14 cam11"),
    ("E5", "8bfe0a1f-da31-4ddd-9455-de0d6a5ef652", "CON", "18:45 cam10 (S3)"),
    ("E6", "a447ff19-068a-4460-855c-3f6d02937860", "CON", "02:46 cam10 (S3)"),
    ("E7", "8367f372-247b-42fd-886d-61bfc600b303", "CON", "12:46 cam11"),
    ("E8", "ae3d87cb-189c-4d80-b56e-d202d92b4e59", "CON", "12:03 cam11"),
]
FEWSHOT_IDS = [
    ("45dc0327-464c-4b70-8c3d-578bed9af07d", "REJ", "passagem proxima da pilha sem deposito"),
    ("290eb292-c7c2-46ae-ab29-d7ba2fa74b8c", "REJ", "passante caminhando, nada deixado"),
    ("0b4aa1a0-ad6c-4063-b5b4-6e813e7e3dbe", "REJ", "passagem na rua, pilha pre-existente sem mudanca"),
]

S3 = boto3.client("s3", region_name="sa-east-1")
TMP = Path("/tmp/flashlite_agent3")
TMP.mkdir(parents=True, exist_ok=True)


def resolve_path(image_url: str, frame_name: str, device_id: str) -> Path | None:
    target = TMP / device_id / frame_name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1000:
        return target
    if "/uploads/" in image_url:
        rel = image_url.split("/uploads/", 1)[-1]
        local = Path("/app/uploads") / rel
        if local.exists():
            return local
        s3_key = f"ocorrencias/{rel}".replace("labeled/", "")
    elif image_url.startswith("https://saira-images.s3"):
        s3_key = urlparse(image_url).path.lstrip("/")
    elif image_url.startswith("/s3-images/"):
        s3_key = image_url[len("/s3-images/"):]
    else:
        return None
    try:
        S3.download_file("saira-images", s3_key, str(target))
        return target if target.stat().st_size > 1000 else None
    except Exception:
        return None


def sample_3(frames: list[dict], device_id: str, selected_name: str | None = None) -> list[Path]:
    if not frames:
        return []
    n = len(frames)
    names = [f["frame_name"] for f in frames]
    if selected_name and selected_name in names:
        sel_i = names.index(selected_name)
        idxs = sorted({0, sel_i, n - 1}) if 2 < sel_i < n - 3 else sorted({0, n // 2, n - 1})
    else:
        idxs = sorted({0, n // 2, n - 1})
    out = []
    for i in idxs:
        f = frames[i]
        p = resolve_path(f["image_url"], f["frame_name"], device_id)
        if p:
            out.append(p)
    return out


def load_event(det_id: str) -> dict | None:
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    su = Path(f"/app/state/detection_summaries/{det_id}.json")
    if not sf.exists():
        return None
    frames_doc = json.loads(sf.read_text())
    summary_doc = json.loads(su.read_text()) if su.exists() else {}
    return {
        "id": det_id,
        "device_id": frames_doc.get("device_id"),
        "frames": frames_doc.get("frames", []),
        "selected_frame_name": frames_doc.get("selected_frame_name") or summary_doc.get("event_frame_name"),
        "evidence_summary": summary_doc.get("evidence_summary") or frames_doc.get("evidence_summary", ""),
    }


def img_part(path: Path) -> types.Part:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
    return types.Part.from_bytes(data=data, mime_type="image/jpeg")


SYS = """Voce e um verificador final de eventos de descarte irregular de lixo.
O sistema ja passou por dois estagios (gate + detail) e o estagio anterior CONFIRMOU este evento.
Sua tarefa: revisar a evidencia e decidir se o operador humano CONFIRMARIA ou REJEITARIA.

Operadores REJEITAM com frequencia eventos onde:
  - pessoas apenas PASSAM perto da pilha sem deixar nada;
  - ciclistas, pedestres, carrinhos atravessam o quadro;
  - a pilha pre-existente NAO muda de volume entre os frames;
  - garis/coletores estao recolhendo lixo (nao depositando);
  - cao/animal mexe na pilha;
  - sombra/iluminacao/lixo solto pelo vento causa "alucinacao" de descarte.

Operadores CONFIRMAM quando ha:
  - transferencia clara de material de pessoa/veiculo/carrinho para a pilha;
  - aumento visivel de volume da pilha apos a passagem de uma pessoa;
  - sacos, moveis, eletronicos, entulho recem-colocados na via.

Voce recebe:
  1. Tres exemplos de eventos REJEITADOS pelo operador (anti-padrao).
  2. O resumo textual produzido pelo Agent-2 (que pode estar confabulando).
  3. 3 frames do evento candidato (primeiro, meio, ultimo).

Responda APENAS JSON:
{
  "should_confirm": true|false,
  "confidence_0_100": int,
  "fp_pattern_match": "pile_unchanged" | "passante" | "coleta" | "animal" | "sombra_lixo_solto" | null,
  "reasoning": "<= 200 chars, pt-BR"
}
"""


def build_request(target_event: dict, fewshots: list[dict]) -> list[types.Part]:
    parts: list[types.Part] = []
    parts.append(types.Part.from_text(text="=== EXEMPLOS DE EVENTOS REJEITADOS PELO OPERADOR ==="))
    for i, fs in enumerate(fewshots, 1):
        parts.append(types.Part.from_text(text=f"\n-- Exemplo REJ #{i} (motivo: {fs['reason']}) --"))
        for p in fs["frames"]:
            parts.append(img_part(p))
        parts.append(types.Part.from_text(
            text=f"Evidence Agent-2: {fs['evidence_summary']}\nDecisao operador: REJEITADO"))
    parts.append(types.Part.from_text(text="\n=== EVENTO A VERIFICAR ==="))
    parts.append(types.Part.from_text(
        text=f"Evidence Agent-2: {target_event['evidence_summary']}\nDecida agora (JSON unico)."))
    for p in target_event["frame_paths"]:
        parts.append(img_part(p))
    return parts


def main():
    fewshots = []
    for det_id, _, reason in FEWSHOT_IDS:
        ev = load_event(det_id)
        if not ev: continue
        fs_paths = sample_3(ev["frames"], ev["device_id"], ev.get("selected_frame_name"))
        if len(fs_paths) < 2: continue
        fewshots.append({"frames": fs_paths, "reason": reason,
                         "evidence_summary": ev["evidence_summary"]})
    print(f"[fewshot] ready: {len(fewshots)}", flush=True)

    test_events = []
    for label, det_id, gt, descr in TEST:
        ev = load_event(det_id)
        if not ev:
            test_events.append({"label": label, "id": det_id, "gt": gt, "descr": descr, "skip": "no_meta"}); continue
        paths = sample_3(ev["frames"], ev["device_id"], ev.get("selected_frame_name"))
        if len(paths) < 2:
            test_events.append({"label": label, "id": det_id, "gt": gt, "descr": descr, "skip": f"only_{len(paths)}"}); continue
        ev.update({"label": label, "gt": gt, "descr": descr, "frame_paths": paths})
        test_events.append(ev)
    print(f"[test] ready: {sum(1 for e in test_events if 'skip' not in e)}/{len(TEST)}", flush=True)

    client = genai.Client(api_key=BENCH_KEY)
    results = []
    total_in = total_out = 0
    cost = 0.0
    for ev in test_events:
        if "skip" in ev:
            results.append({"label": ev["label"], "id": ev["id"], "gt": ev["gt"],
                            "descr": ev["descr"], "skip": ev["skip"]})
            continue
        parts = build_request(ev, fewshots)
        t0 = time.monotonic()
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[types.Content(parts=parts, role="user")],
                config=types.GenerateContentConfig(
                    system_instruction=SYS,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
        except Exception as exc:
            print(f"  {ev['label']} ERROR: {exc}", flush=True)
            results.append({"label": ev["label"], "id": ev["id"], "gt": ev["gt"],
                            "descr": ev["descr"], "error": str(exc)})
            continue
        latency = int((time.monotonic() - t0) * 1000)
        u = resp.usage_metadata
        in_tok = u.prompt_token_count or 0
        out_tok = (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
        total_in += in_tok; total_out += out_tok
        cost += in_tok * FLASH_LITE_IN_PRICE + out_tok * FLASH_LITE_OUT_PRICE
        try:
            obj = json.loads(resp.text)
        except Exception:
            obj = {"raw": (resp.text or "")[:300]}
        print(f"  {ev['label']} {ev['descr']:<20s} gt={ev['gt']} "
              f"flashlite={'CON' if obj.get('should_confirm') else 'REJ'} "
              f"conf={obj.get('confidence_0_100')} pat={obj.get('fp_pattern_match')} "
              f"({latency}ms) | {str(obj.get('reasoning',''))[:80]}", flush=True)
        results.append({"label": ev["label"], "id": ev["id"], "gt": ev["gt"],
                        "descr": ev["descr"], "response": obj, "latency_ms": latency,
                        "in_tok": in_tok, "out_tok": out_tok})

    hits = counted = 0
    for r in results:
        if "response" not in r: continue
        counted += 1
        pred = "CON" if r["response"].get("should_confirm") else "REJ"
        if pred == r["gt"]: hits += 1
    print()
    print(f"=== Flash Lite as Agent-3 — accuracy: {hits}/{counted} ===")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} (avg ${cost/max(counted,1):.4f}/event)")
    out_path = Path("/tmp/flashlite_agent3_results.json")
    out_path.write_text(json.dumps({"model": MODEL,
                                    "accuracy": f"{hits}/{counted}",
                                    "total_cost_usd": round(cost, 6),
                                    "results": results}, ensure_ascii=False, indent=2))
    print(f"saved: {out_path}")


if __name__ == "__main__":
    sys.exit(main())
