#!/usr/bin/env python3
"""Gemini Pro 2.5 as Agent-2 (detail) replacement — full eval on 52 events.

Mirror of sonnet_as_detail.py but using google-genai + GEMINI_TEST_API_KEY.
Same per-camera prompt match (V1 for cam_10, V3 for cam_11), 12 keyframes/event.

Pricing Gemini 2.5 Pro: in $1.25/M, out $10/M.
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
import psycopg2
from google import genai
from google.genai import types
from PIL import Image

MODEL = "gemini-2.5-pro"
PRO_IN_PRICE = 1.25 / 1e6
PRO_OUT_PRICE = 10.0 / 1e6
N_FRAMES = 12

BENCH_KEY = os.environ["GEMINI_TEST_API_KEY"]
S3 = boto3.client("s3", region_name="sa-east-1")
CLIENT = genai.Client(api_key=BENCH_KEY)

TMP = Path("/tmp/pro_detail")
TMP.mkdir(parents=True, exist_ok=True)

DEVICE_BY_CAM = {10: "esp32_001", 11: "esp32_002"}
PROMPT_BY_CAM = {10: "V1", 11: "V3"}


# V1 detail system prompt
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

# V3 detail system prompt (postura-based)
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


def img_part(path: Path) -> types.Part:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        data = buf.getvalue()
    return types.Part.from_bytes(data=data, mime_type="image/jpeg")


def call_pro(paths, frame_names, cam_id, prompt_version: str):
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
    parts = [types.Part.from_text(text=intro)]
    for p in paths:
        parts.append(img_part(p))
    t0 = time.monotonic()
    resp = CLIENT.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=parts, role="user")],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEMS[prompt_version],
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
    events = fetch_events()
    print(f"[fetch] {len(events)} events", flush=True)

    cache_path = Path("/tmp/pro_as_detail_cache.json")
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
            print(f"  {ev['id'][:8]}: only {len(paths)} frames", flush=True)
            continue
        prompt_version = PROMPT_BY_CAM.get(ev["cam"], "V1")
        try:
            obj, in_tok, out_tok, latency = call_pro(paths, names, ev["cam"], prompt_version)
        except Exception as exc:
            print(f"  {ev['id'][:8]} ERROR: {exc}", flush=True)
            continue
        ev_cost = in_tok * PRO_IN_PRICE + out_tok * PRO_OUT_PRICE
        total_in += in_tok
        total_out += out_tok
        cost += ev_cost
        gt = "CON" if ev["status"] == "CONFIRMADO" else "REJ"
        pred = "CON" if obj.get("infraction_confirmed") else "REJ"
        row = {"id": ev["id"], "ts": ev["ts"], "cam": ev["cam"], "gt": gt,
               "pred": pred, "confidence": obj.get("confidence_0_100"),
               "waste_type": obj.get("waste_type"),
               "offender_detected": obj.get("offender_detected"),
               "evidence_summary": (obj.get("evidence_summary") or "")[:200],
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

    n = len(results)
    tp = sum(1 for r in results if r["pred"] == "CON" and r["gt"] == "CON")
    tn = sum(1 for r in results if r["pred"] == "REJ" and r["gt"] == "REJ")
    fp = sum(1 for r in results if r["pred"] == "CON" and r["gt"] == "REJ")
    fn = sum(1 for r in results if r["pred"] == "REJ" and r["gt"] == "CON")
    acc = (tp + tn) / max(n, 1)
    print()
    print(f"=== Gemini Pro 2.5 as Agent-2 detail — n={n} ===")
    print(f"acc={acc:.2%}  TP={tp} TN={tn} FP={fp} FN={fn}")
    print(f"precision (CON)={tp/max(tp+fp,1):.2%}  recall (CON)={tp/max(tp+fn,1):.2%}  specificity (REJ)={tn/max(tn+fp,1):.2%}")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} (avg ${cost/max(n,1):.4f}/event)")

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

    out = Path("/tmp/pro_as_detail_results.json")
    out.write_text(json.dumps({
        "model": MODEL, "n": n, "acc": acc,
        "confusion": {"TP": tp, "TN": tn, "FP": fp, "FN": fn},
        "cost_usd": round(cost, 6), "avg_cost_per_event": round(cost / max(n, 1), 6),
        "results": results,
    }, ensure_ascii=False, indent=2))
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    sys.exit(main())
