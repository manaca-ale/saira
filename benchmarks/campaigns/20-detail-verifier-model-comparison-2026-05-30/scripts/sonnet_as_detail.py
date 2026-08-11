#!/usr/bin/env python3
"""Sonnet 4.6 as Agent-2 (detail) replacement — full eval on 52 events.

Uses the V1 detail system prompt from detector_gemini.py SYSTEM_PROMPT.
12 keyframes per event sampled evenly from the window.
Compares infraction_confirmed vs operator REJ/CON.

Bedrock pricing Sonnet 4.6: in $3/M, out $15/M.

Runs inside worker container with AWS temp creds via env vars + boto3.
"""
from __future__ import annotations
import base64
import io
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
import psycopg2
from PIL import Image

REGION = "us-east-1"
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
N_FRAMES = 12
SONNET_IN_PRICE = 3.0 / 1e6
SONNET_OUT_PRICE = 15.0 / 1e6

S3 = boto3.client("s3", region_name="sa-east-1")
BEDROCK = boto3.client("bedrock-runtime", region_name=REGION)

TMP = Path("/tmp/sonnet_detail")
TMP.mkdir(parents=True, exist_ok=True)

DEVICE_BY_CAM = {10: "esp32_001", 11: "esp32_002"}

# Per-camera prompt selection (matches prod cascade: cam_10 V1, cam_11 V3+B3 gate
# implies V3 detail for fairness with the more permissive flow).
PROMPT_BY_CAM = {10: "V1", 11: "V3"}


# V1 detail system prompt (cloned from detector_gemini.py SYSTEM_PROMPT)
SYS_V1 = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos estacionados,
infraestrutura municipal fixa (postes, lixeiras com tampa, bollards, marcacoes viarias),
PILHAS DE LIXO PRE-EXISTENTES de janelas anteriores, e iluminacao natural variavel.
Estes elementos sao NORMAIS e ESPERADOS — uma pilha que ja estava no primeiro frame
e PERMANECE inalterada no ultimo frame NAO e infracao.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos/permanentes visiveis no primeiro frame.
2. DELTA TEMPORAL: Identifique o que MUDOU entre o primeiro e o ultimo frame.
3. CLASSIFICACAO: Cada mudanca e SOMBRA_ILUMINACAO, OBJETO_EM_MOVIMENTO, ou COMPORTAMENTO_DESCARTE.
4. DECISAO: infraction_confirmed=true quando houver COMPORTAMENTO_DESCARTE confirmado.

COMPORTAMENTO_DESCARTE e confirmado quando QUALQUER das seguintes evidencias e visivel:
A) Material novo claramente visivel no chao que surgiu durante a sequencia.
B) Veiculo PARADO (mesma posicao em 2+ frames) proximo a area de residuos com pessoa
   ESTACIONARIA entre o veiculo e o chao, carregando ou manuseando material.
C) Veiculo com cacamba aberta/levantada proximo a pilha de residuos, descarregando.

SINAL-CHAVE: Veiculos e pessoas realizando descarte ficam ESTACIONARIOS entre os frames
(mesma posicao relativa). Trafego normal mostra veiculos/pessoas em POSICOES DIFERENTES
entre frames. Use esta diferenca para distinguir descarte de trafego.

Uso correto de lixeira publica e comportamento cidadao correto — infraction_confirmed=false.
Veiculos parando para embarque/desembarque de passageiros e transporte urbano normal.
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_detected descreve somente a capacidade de identificar o autor/veiculo.
Se um campo nao puder ser inferido com seguranca, retorne null.

Schema do JSON de resposta:
{
  "baseline_description": "<= 400 chars",
  "infraction_confirmed": true|false,
  "confidence_0_100": <int 0-100>,
  "evidence_summary": "<= 600 chars, resumo factual breve",
  "waste_type": "Entulho"|"Lixo domiciliar"|"Poda"|"Plastico"|null,
  "offender_detected": true|false,
  "raw_reason_codes": ["..."]|null
}
""".strip()


# V3 detail system prompt (cloned from _prompts_v3.py SYSTEM_PROMPT_V3)
SYS_V3 = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos
estacionados, infraestrutura municipal fixa (postes, lixeiras com tampa, bollards,
marcacoes viarias), PILHAS DE LIXO PRE-EXISTENTES de janelas anteriores, e
iluminacao natural variavel. Estes elementos sao NORMAIS — uma pilha que ja
estava no primeiro frame e PERMANECE no ultimo NAO e infracao.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos no primeiro frame.
2. POSTURA: Identifique a pessoa mais relevante e sua postura (inclinada/agachada
   na pilha, em pe perto, atravessando, levando coisas do chao, etc).
3. DELTA TEMPORAL: O que MUDOU entre o primeiro e o ultimo frame?
4. DECISAO: infraction_confirmed=true se houver QUALQUER UMA das evidencias:
   - Pessoa em postura de deposito (inclinada/agachada na pilha) com objeto nas
     maos em algum frame e maos vazias/diferente em outro;
   - Pessoa saindo da pilha sem o que trouxe (chegou com saco, saiu sem);
   - Veiculo parado com cacamba aberta descarregando entulho;
   - Material novo CLARAMENTE visivel no chao (>=0.3 m³, inequivoco).

DISCRIMINADOR PRIMARIO — POSTURA DA PESSOA (mais confiavel que delta de pilha):
- inclinada/agachada PERTO da pilha COM saco/objeto = DESCARTE
- atravessando em linha reta = transeunte, NAO descarte
- em pe parada perto da pilha sem manuseio = neutro
- pegando objetos DA pilha = COLETA (informal)

DISCRIMINADOR SECUNDARIO — DIRECAO DO MATERIAL:
- material indo DO veiculo/pessoa PARA o chao = DESCARTE
- material indo DO chao PARA o veiculo/carroca = COLETA
- carroca presente = NEUTRO (carroceiros descartam e coletam — decide pela postura)

IMPORTANTE — RESOLUCAO DA CAMERA:
Descartes pedestres reais geralmente sao 0.01-0.15 m³ (1 saco pequeno). Isso e
INVISIVEL na resolucao desta camera. O primeiro e ultimo frame podem parecer
IDENTICOS mesmo quando houve descarte. NAO use ausencia de crescimento da
pilha como evidencia contra descarte. Confie na POSTURA e na PRESENCA de pessoa
junto a pilha por varios frames consecutivos.

ATIVIDADES QUE NAO SAO DESCARTE (infraction_confirmed=false):
- Coleta municipal: caminhao COMPACTADOR EMLURB (hopper traseiro) parado,
  pessoas levando sacos DO CHAO PARA o caminhao. Pilha DIMINUI.
- Poda municipal: equipe com vassouras/ancinhos juntando restos vegetais
  do chao em pilha organizada ou caminhao.
- Catador/carroceiro COLETANDO: pessoa com carroca de madeira levando
  reciclaveis DO CHAO PARA a carroca, com PILHA DIMINUINDO.
  ATENCAO: se o carroceiro DEIXOU restos novos no chao, isso e DESCARTE.
- Transeuntes que so passam pela cena (atravessam em linha reta, posicoes
  diferentes entre frames, nao param junto da pilha).
- Pessoas paradas conversando na calcada sem manuseio de material.

ATIVIDADES QUE SAO DESCARTE (infraction_confirmed=true):
- Pessoa INCLINADA ou AGACHADA junto a pilha com saco/objeto nas maos em
  pelo menos 1 frame e maos vazias/diferente em outro, MESMO se a pilha
  parecer visualmente identica entre primeiro e ultimo frame.
- Veiculo PARADO com cacamba aberta/levantada descarregando entulho no chao.
- Pessoa(s) ESTACIONARIA(s) levando sacos/objetos DO veiculo PARA o chao,
  inclusive uniformizadas. UNIFORME NAO ISENTA DESCARTE.

UNIFORME NAO E DISCRIMINADOR. Trabalhador uniformizado (colete laranja
EMLURB, camisa de obra, jaleco de mudanca, uniforme de entrega) pode estar
COLETANDO ou DESCARTANDO. Decide pela POSTURA (inclinado depositando vs
recolhendo do chao para veiculo) e pela DIRECAO DO MATERIAL.

Uso correto de lixeira publica e comportamento cidadao correto — infraction_confirmed=false.
Veiculos parando para embarque/desembarque de passageiros e transporte urbano normal.
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_detected descreve somente a capacidade de identificar o autor/veiculo.
Se um campo nao puder ser inferido com seguranca, retorne null.

Schema do JSON de resposta:
{
  "baseline_description": "<= 400 chars",
  "infraction_confirmed": true|false,
  "confidence_0_100": <int 0-100>,
  "evidence_summary": "<= 600 chars, resumo factual breve",
  "waste_type": "Entulho"|"Lixo domiciliar"|"Poda"|"Plastico"|null,
  "offender_detected": true|false,
  "raw_reason_codes": ["..."]|null
}
""".strip()

SYSTEMS = {"V1": SYS_V1, "V3": SYS_V3}


def resolve_frame(image_url: str, frame_name: str, device_id: str) -> Path | None:
    target = TMP / "frames" / device_id / frame_name
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


def fetch_events():
    conn = psycopg2.connect(host="saira-db-prod", user="postgres",
                            password="postgres", dbname="saira_db")
    cur = conn.cursor()
    cur.execute("""
        SELECT id::text, timestamp::text, camera_id, status::text
        FROM detections
        WHERE status IN ('REJEITADO', 'CONFIRMADO')
          AND camera_id IN (10, 11)
        ORDER BY timestamp DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "ts": r[1], "cam": r[2], "status": r[3]} for r in rows]


def load_event(det_id: str):
    sf = Path(f"/app/state/detection_frames/{det_id}.json")
    if not sf.exists():
        return None
    return json.loads(sf.read_text())


def sample_n(frames, n):
    if len(frames) <= n:
        return list(range(len(frames)))
    return [int(round(i * (len(frames) - 1) / (n - 1))) for i in range(n)]


def image_block(path: Path) -> dict:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
    return {"image": {"format": "jpeg", "source": {"bytes": data}}}


def build_content(paths: list[Path], frame_names: list[str], cam_id: int) -> list[dict]:
    blocks: list[dict] = []
    cam_ctx = {
        10: "cam_imbiribeira (Imbiribeira, Recife) — ponto de descarte cronico em calcada lateral",
        11: "cam_mangabeira (Mangabeira, Recife) — ponto de descarte cronico com pilha permanente",
    }
    intro = (
        f"Voce recebe {len(paths)} frames sequenciais (chronological order, "
        f"primeiro=earliest, ultimo=latest) de uma camera fixa.\n"
        f"Contexto da camera: {cam_ctx.get(cam_id, 'sem contexto')}\n"
        f"Frame names (ordem): {', '.join(frame_names)}\n\n"
        "Analise a sequencia e retorne JSON estruturado (apenas JSON, sem texto antes ou depois)."
    )
    blocks.append({"text": intro})
    for p in paths:
        blocks.append(image_block(p))
    return blocks


def call_sonnet(content, prompt_version: str):
    t0 = time.monotonic()
    resp = BEDROCK.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEMS[prompt_version]}],
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"temperature": 0.0, "maxTokens": 1024},
    )
    latency = int((time.monotonic() - t0) * 1000)
    text = resp["output"]["message"]["content"][0]["text"]
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        obj = json.loads(text.strip())
    except Exception:
        obj = {"raw": text[:400]}
    return obj, resp.get("usage", {}), latency


def main():
    events = fetch_events()
    print(f"[fetch] {len(events)} events", flush=True)

    # Resume cache (in case mid-run interruption)
    cache_path = Path("/tmp/sonnet_as_detail_cache.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    print(f"[cache] {len(cache)} done", flush=True)

    results = []
    total_in = total_out = 0
    cost = 0.0
    for i, ev in enumerate(events, 1):
        device_id = DEVICE_BY_CAM.get(ev["cam"])
        if not device_id:
            continue
        det = load_event(ev["id"])
        if not det or not det.get("frames"):
            continue
        if ev["id"] in cache:
            results.append(cache[ev["id"]])
            total_in += cache[ev["id"]].get("in_tok", 0)
            total_out += cache[ev["id"]].get("out_tok", 0)
            cost += cache[ev["id"]].get("cost_usd", 0)
            continue

        frames = det["frames"]
        idxs = sample_n(frames, N_FRAMES)
        paths = []
        names = []
        for k in idxs:
            f = frames[k]
            p = resolve_frame(f["image_url"], f["frame_name"], device_id)
            if p:
                paths.append(p)
                names.append(f["frame_name"])
        if len(paths) < 4:
            print(f"  {ev['id'][:8]}: only {len(paths)} frames resolved", flush=True)
            continue
        content = build_content(paths, names, ev["cam"])
        prompt_version = PROMPT_BY_CAM.get(ev["cam"], "V1")
        try:
            obj, usage, latency = call_sonnet(content, prompt_version)
        except Exception as exc:
            print(f"  {ev['id'][:8]} ERROR: {exc}", flush=True)
            continue
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        ev_cost = in_tok * SONNET_IN_PRICE + out_tok * SONNET_OUT_PRICE
        total_in += in_tok
        total_out += out_tok
        cost += ev_cost
        gt = "CON" if ev["status"] == "CONFIRMADO" else "REJ"
        pred = "CON" if obj.get("infraction_confirmed") else "REJ"
        row = {"id": ev["id"], "ts": ev["ts"], "cam": ev["cam"], "gt": gt,
               "pred": pred, "confidence": obj.get("confidence_0_100"),
               "waste_type": obj.get("waste_type"),
               "offender_detected": obj.get("offender_detected"),
               "evidence_summary": obj.get("evidence_summary", "")[:200],
               "prompt_version": prompt_version,
               "in_tok": in_tok, "out_tok": out_tok, "latency_ms": latency,
               "cost_usd": round(ev_cost, 6),
               "n_frames_used": len(paths)}
        results.append(row)
        cache[ev["id"]] = row
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))

        mark = "OK" if pred == gt else "MISS"
        print(f"  {i:>2}/{len(events)} {ev['ts'][:16]} cam_{ev['cam']} [{prompt_version}] "
              f"gt={gt} pred={pred} conf={obj.get('confidence_0_100')} {mark} "
              f"({latency}ms in={in_tok} out={out_tok} ${ev_cost:.4f})", flush=True)

    # scoring
    n = len(results)
    tp = sum(1 for r in results if r["pred"] == "CON" and r["gt"] == "CON")
    tn = sum(1 for r in results if r["pred"] == "REJ" and r["gt"] == "REJ")
    fp = sum(1 for r in results if r["pred"] == "CON" and r["gt"] == "REJ")
    fn = sum(1 for r in results if r["pred"] == "REJ" and r["gt"] == "CON")
    acc = (tp + tn) / max(n, 1)
    print()
    print(f"=== Sonnet 4.6 as Agent-2 detail — n={n} ===")
    print(f"acc={acc:.2%}  TP={tp} TN={tn} FP={fp} FN={fn}")
    print(f"precision (CON)={tp/max(tp+fp,1):.2%}  recall (CON)={tp/max(tp+fn,1):.2%}  specificity (REJ)={tn/max(tn+fp,1):.2%}")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} (avg ${cost/max(n,1):.4f}/event)")

    # per-camera
    print("\n=== per-camera ===")
    for cam in (10, 11):
        sub = [r for r in results if r["cam"] == cam]
        if not sub: continue
        s_tp = sum(1 for r in sub if r["pred"] == "CON" and r["gt"] == "CON")
        s_tn = sum(1 for r in sub if r["pred"] == "REJ" and r["gt"] == "REJ")
        s_fp = sum(1 for r in sub if r["pred"] == "CON" and r["gt"] == "REJ")
        s_fn = sum(1 for r in sub if r["pred"] == "REJ" and r["gt"] == "CON")
        s_n = len(sub)
        print(f"  cam_{cam} n={s_n} acc={(s_tp+s_tn)/s_n:.2%} TP={s_tp} TN={s_tn} FP={s_fp} FN={s_fn}")

    out = Path("/tmp/sonnet_as_detail_results.json")
    out.write_text(json.dumps({
        "model": MODEL_ID, "n": n, "acc": acc,
        "confusion": {"TP": tp, "TN": tn, "FP": fp, "FN": fn},
        "cost_usd": round(cost, 6), "avg_cost_per_event": round(cost / max(n, 1), 6),
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
