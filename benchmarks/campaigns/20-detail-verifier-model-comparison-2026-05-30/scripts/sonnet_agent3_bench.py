#!/usr/bin/env python3
"""Sonnet 4.6 via AWS Bedrock — same Agent-3 prompt as agent3_proto.py.

Compares against Gemini Pro 2.5 result (87.5% on 8 events, $0.015/call, ~10s).

Sonnet 4.6 Bedrock pricing: input $3/M, output $15/M.

Runs locally on Windows. Frames are cached in c:/saira/.tmp/sonnet_bench/.
Fetches missing frames via:
  - `ssh saira-prod docker exec ... cat` for /app/uploads/* (today's events)
  - boto3 S3 (saira-images) for migrated frames
JSON metadata via ssh+docker cat from /app/state/detection_{frames,summaries}/.
"""
from __future__ import annotations
import base64
import io
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
from PIL import Image

TMP = Path(r"c:\saira\.tmp\sonnet_bench")
TMP.mkdir(parents=True, exist_ok=True)
FRAMES = TMP / "frames"
META = TMP / "meta"
FRAMES.mkdir(exist_ok=True)
META.mkdir(exist_ok=True)

MODEL_ID = "us.anthropic.claude-sonnet-4-6"
REGION = "us-east-1"
PROFILE = "codex-ops"

# Sonnet 4.6 Bedrock pricing
SONNET_IN_PRICE = 3.0 / 1e6
SONNET_OUT_PRICE = 15.0 / 1e6

# Same 8 events as agent3_proto.py (Gemini Pro bench)
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

SESSION = boto3.Session(profile_name=PROFILE, region_name=REGION)
S3 = SESSION.client("s3")
BEDROCK = SESSION.client("bedrock-runtime")


def ssh_docker_cat(remote_path: str) -> bytes | None:
    """Cat a file inside saira-yolo-worker-prod and return bytes."""
    try:
        result = subprocess.run(
            ["ssh", "saira-prod", "docker", "exec", "saira-yolo-worker-prod",
             "cat", remote_path],
            capture_output=True, check=True, timeout=60,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def load_event_meta(det_id: str) -> dict | None:
    cache_path = META / f"{det_id}.json"
    sum_cache = META / f"{det_id}_sum.json"
    if cache_path.exists() and sum_cache.exists():
        return {"frames_doc": json.loads(cache_path.read_text(encoding="utf-8")),
                "summary_doc": json.loads(sum_cache.read_text(encoding="utf-8"))}
    fbytes = ssh_docker_cat(f"/app/state/detection_frames/{det_id}.json")
    sbytes = ssh_docker_cat(f"/app/state/detection_summaries/{det_id}.json")
    if not fbytes:
        return None
    cache_path.write_bytes(fbytes)
    if sbytes:
        sum_cache.write_bytes(sbytes)
    return {"frames_doc": json.loads(fbytes),
            "summary_doc": json.loads(sbytes) if sbytes else {}}


def resolve_frame(image_url: str, frame_name: str, device_id: str) -> Path | None:
    """Cache local; fetch via ssh docker cat or S3."""
    target = FRAMES / device_id / frame_name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1000:
        return target
    if "/uploads/" in image_url:
        rel = image_url.split("/uploads/", 1)[-1]
        data = ssh_docker_cat(f"/app/uploads/{rel}")
        if data and len(data) > 1000:
            target.write_bytes(data)
            return target
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
    except Exception as exc:
        print(f"    [s3] failed {s3_key}: {exc}", file=sys.stderr)
        return None


def sample_3(meta: dict, device_id: str) -> list[Path]:
    """First / detail's selected_frame (if not edge) / last."""
    frames = meta["frames_doc"].get("frames", [])
    if not frames:
        return []
    n = len(frames)
    sel = meta["frames_doc"].get("selected_frame_name") or meta["summary_doc"].get("event_frame_name")
    names = [f["frame_name"] for f in frames]
    if sel and sel in names:
        sel_i = names.index(sel)
        idxs = sorted({0, sel_i, n - 1}) if 2 < sel_i < n - 3 else sorted({0, n // 2, n - 1})
    else:
        idxs = sorted({0, n // 2, n - 1})
    out = []
    for i in idxs:
        f = frames[i]
        p = resolve_frame(f["image_url"], f["frame_name"], device_id)
        if p:
            out.append(p)
    return out


def image_block(path: Path) -> dict:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
    return {"image": {"format": "jpeg", "source": {"bytes": data}}}


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

Responda APENAS JSON valido (sem texto antes ou depois):
{
  "should_confirm": true|false,
  "confidence_0_100": <int>,
  "fp_pattern_match": "pile_unchanged" | "passante" | "coleta" | "animal" | "sombra_lixo_solto" | null,
  "reasoning": "<= 200 chars, pt-BR"
}
"""


def build_content(target_event: dict, fewshots: list[dict]) -> list[dict]:
    blocks: list[dict] = [{"text": "=== EXEMPLOS DE EVENTOS REJEITADOS PELO OPERADOR ==="}]
    for i, fs in enumerate(fewshots, 1):
        blocks.append({"text": f"\n-- Exemplo REJ #{i} (motivo: {fs['reason']}) --"})
        for p in fs["frames"]:
            blocks.append(image_block(p))
        blocks.append({"text": f"Evidence Agent-2: {fs['evidence_summary']}\nDecisao operador: REJEITADO"})
    blocks.append({"text": "\n=== EVENTO A VERIFICAR ==="})
    blocks.append({"text": f"Evidence Agent-2: {target_event['evidence_summary']}\nDecida agora (JSON unico)."})
    for p in target_event["frame_paths"]:
        blocks.append(image_block(p))
    return blocks


def call_sonnet(content: list[dict]) -> tuple[dict, dict, int]:
    t0 = time.monotonic()
    resp = BEDROCK.converse(
        modelId=MODEL_ID,
        system=[{"text": SYS}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"temperature": 0.0, "maxTokens": 1024},
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    text = resp["output"]["message"]["content"][0]["text"]
    try:
        # strip code fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        obj = json.loads(text.strip())
    except Exception:
        obj = {"raw": text[:300]}
    return obj, resp.get("usage", {}), latency_ms


def main():
    DEVICE_BY_CAM = {"esp32_001": "esp32_001", "esp32_002": "esp32_002"}

    print("[fewshot] loading ...", flush=True)
    fewshots = []
    for det_id, _, reason in FEWSHOT_IDS:
        meta = load_event_meta(det_id)
        if not meta:
            print(f"  fewshot MISSING {det_id}", flush=True); continue
        device_id = meta["frames_doc"]["device_id"]
        paths = sample_3(meta, device_id)
        if len(paths) < 2:
            print(f"  fewshot frames missing for {det_id}", flush=True); continue
        evid = meta["summary_doc"].get("evidence_summary") or meta["frames_doc"].get("evidence_summary", "")
        fewshots.append({"frames": paths, "reason": reason, "evidence_summary": evid})
    print(f"  ready: {len(fewshots)}", flush=True)

    print("[test] loading ...", flush=True)
    test_events = []
    for label, det_id, gt, descr in TEST:
        meta = load_event_meta(det_id)
        if not meta:
            print(f"  {label}: MISSING", flush=True)
            test_events.append({"label": label, "id": det_id, "gt": gt, "descr": descr, "skip": "no_meta"}); continue
        device_id = meta["frames_doc"]["device_id"]
        paths = sample_3(meta, device_id)
        if len(paths) < 2:
            print(f"  {label}: only {len(paths)} frames", flush=True)
            test_events.append({"label": label, "id": det_id, "gt": gt, "descr": descr, "skip": "no_frames"}); continue
        evid = meta["summary_doc"].get("evidence_summary") or meta["frames_doc"].get("evidence_summary", "")
        test_events.append({"label": label, "id": det_id, "gt": gt, "descr": descr,
                            "frame_paths": paths, "evidence_summary": evid})
    print(f"  ready: {sum(1 for e in test_events if 'skip' not in e)}/{len(TEST)}", flush=True)

    print(f"\n[bench] model={MODEL_ID}\n", flush=True)
    results = []
    total_in = total_out = 0
    cost = 0.0
    for ev in test_events:
        if "skip" in ev:
            results.append({**ev}); continue
        content = build_content(ev, fewshots)
        try:
            obj, usage, latency = call_sonnet(content)
        except Exception as exc:
            print(f"  {ev['label']} ERROR: {exc}", flush=True)
            results.append({**ev, "error": str(exc)}); continue
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        total_in += in_tok; total_out += out_tok
        cost += in_tok * SONNET_IN_PRICE + out_tok * SONNET_OUT_PRICE
        print(f"  {ev['label']} {ev['descr']:<20s} gt={ev['gt']} "
              f"sonnet={'CON' if obj.get('should_confirm') else 'REJ'} "
              f"conf={obj.get('confidence_0_100')} pat={obj.get('fp_pattern_match')} "
              f"({latency}ms in={in_tok} out={out_tok}) | {str(obj.get('reasoning',''))[:80]}", flush=True)
        results.append({**ev, "response": obj, "latency_ms": latency,
                        "in_tok": in_tok, "out_tok": out_tok,
                        "frame_paths": [str(p) for p in ev.get("frame_paths", [])]})

    hits = counted = 0
    for r in results:
        if "response" not in r: continue
        counted += 1
        pred = "CON" if r["response"].get("should_confirm") else "REJ"
        if pred == r["gt"]: hits += 1
    print()
    print(f"=== Sonnet 4.6 (Bedrock) — accuracy: {hits}/{counted} ===")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} "
          f"(avg ${cost/max(counted,1):.4f}/event)")

    out = Path(r"c:\saira\.tmp\sonnet_bench_results.json")
    out.write_text(json.dumps({"model": MODEL_ID, "accuracy": f"{hits}/{counted}",
                               "total_cost_usd": round(cost, 6),
                               "results": results}, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
    print(f"saved: {out}")


if __name__ == "__main__":
    sys.exit(main())
