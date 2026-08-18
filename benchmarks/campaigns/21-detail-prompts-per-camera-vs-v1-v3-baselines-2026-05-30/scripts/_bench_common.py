#!/usr/bin/env python3
"""Shared bench utilities for campanha 21 (per-camera detail prompts).

Reused by flash_as_detail_per_camera.py and pro_as_detail_per_camera.py.
Same 52-event sample as camp 20, same 12-keyframe sampling, same DB query.

Inline copies of DETAIL_PROMPT_V3_IMBIRIBEIRA and DETAIL_PROMPT_V3_MANGABEIRA
(sourced from prompts/*.md) so this script is self-contained and doesn't depend
on prod code being updated.
"""
from __future__ import annotations
import io
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
import psycopg2
from PIL import Image

DEVICE_BY_CAM = {10: "esp32_001", 11: "esp32_002"}
# Prompt routing per device id — mirrors what gate already does for esp32_002.
PROMPT_BY_CAM = {10: "IMBIRIBEIRA", 11: "MANGABEIRA"}

# === Inline prompt copies ===================================================
# Synced from prompts/detail-v3-esp32_001-imbiribeira.md and
# prompts/detail-v3-esp32_002-mangabeira.md on 2026-05-30.

DETAIL_PROMPT_V3_MANGABEIRA = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Local: ponto cronico de descarte em Mangabeira, Recife (Av. Prof. Jose dos Anjos).
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos
estacionados, infraestrutura municipal fixa (postes, lixeiras, bollards),
PILHA DE LIXO PRE-EXISTENTE no canteiro lateral (esta pilha esta SEMPRE presente
neste ponto), e iluminacao variavel. A pilha pre-existente e ESPERADA — sua
presenca NAO indica infracao. O que muda e o COMPORTAMENTO HUMANO ao redor dela.

PERFIL DOS DESCARTES REAIS NESTA CAMERA (97% pedestres):
A esmagadora maioria dos descartes confirmados aqui sao PEDESTRES com volumes
MINUSCULOS (0,01 a 0,4 m³, mediana ~0,05 m³ = 1 sacola pequena). Isso e
INVISIVEL na resolucao da camera. O primeiro e ultimo frame podem parecer
IDENTICOS mesmo apos um descarte real. Confie na POSTURA + FLUXO DE MATERIAL
da pessoa, nao na mudanca visivel da pilha.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos no primeiro
   frame (pilha pre-existente, postes, lixeiras, veiculos estacionados).
2. PESSOA RELEVANTE: Identifique a pessoa que MAIS interage com a pilha. Se
   ninguem interage com a pilha, infraction_confirmed=false.
3. POSTURA + FLUXO: Analise a postura da pessoa relevante em todos os frames
   onde aparece, e a direcao do material que carrega.
4. CHECAR ANTI-PADROES: Antes de decidir CON, verifique a lista de anti-padroes
   abaixo. Muitos casos parecidos com descarte sao na verdade COLETA/passagem.
5. DECISAO: infraction_confirmed=true SO se houver evidencia clara de DESCARTE
   pedestre (criterios abaixo). Em caso de duvida razoavel, false.

PADROES DE DESCARTE REAL NESTA CAMERA (=true):
A) Pessoa AGACHADA ou INCLINADA junto a pilha com saco/objeto nas maos em pelo
   menos um frame, e em outro frame as maos estao vazias ou diferentes.
B) Pessoa em pe largando um saco/objeto e seguindo (transicao maos cheias->vazias).
C) Pessoa "retirando conteudo de uma sacola/balde" sobre a pilha (esvaziar
   recipiente na pilha).
D) Pessoa com CARRINHO DE MAO ou BICICLETA CARREGADA posicionado AO LADO da
   pilha, com material indo DE dentro do carrinho/bicicleta PARA o chao/pilha.
E) Pessoa carregando objetos grandes (taboa, eletronico, movel) e os depositando
   na pilha ou no chao.
F) ATENCAO: UNIFORME LARANJA EMLURB ja foi observado em descarte real. Nao
   isenta. Decide pela postura e direcao do material.
G) ATENCAO: descarte real PODE ocorrer DURANTE atividade de limpeza municipal.
   Existe caso confirmado de "pessoa passa pelo local enquanto pessoal da
   prefeitura limpa e descarta". Avalie cada pessoa individualmente.

PADROES DE FALSO POSITIVO COMUNS NESTA CAMERA (=false):
Estes sao os 64 falsos positivos historicos que o operador rejeitou aqui:

1) COLETA/LIMPEZA/PODA EMLURB (44% dos FPs, n=28):
   - Caminhao compactador EMLURB parado, pessoas com sacos/vassouras/ancinhos
     levando material DO CHAO PARA o caminhao
   - Equipe de poda com vassouras juntando restos vegetais
   - Pilha DIMINUI ou desaparece durante a sequencia
   - Vocabulario tipico: "estavam retirando o lixo", "limpando restos de poda",
     "realizando a poda", "pessoal da prefeitura limpando"
   - Frequentemente envolvem multiplas pessoas uniformizadas + veiculo municipal
   - REGRA: pilha diminuindo + fluxo material chao->caminhao = COLETA, false.

2) PASSANTES (25% dos FPs, n=16):
   - Pessoas, ciclistas, motos, carros atravessando o quadro em LINHA RETA
   - Posicoes MUITO diferentes entre frames (caminhando, nao parando)
   - Nao param junto a pilha; cruzam e seguem
   - Vocabulario: "apenas pessoas passando", "homem passando de bicicleta",
     "pessoa passando com um carrinho", "pessoas e veiculos passando"
   - REGRA: posicoes diferentes entre frames + sem parada = passante, false.

3) PESSOAS COM SACO QUE NAO DEPOSITAM (5% dos FPs, n=3):
   - Pessoa atravessa o quadro CARREGANDO saco/sacola mas NAO para na pilha
   - "Homem passa com sacos de lixo na mao mas nao realiza o descarte"
   - "Bicicleta carregada de sacos (ele nao realiza um descarte)"
   - REGRA: carregar saco NAO basta; precisa de PARADA + transicao maos
     cheias->vazias junto a pilha. Sem isso, false.

4) CATADOR/CARROCEIRO VASCULHANDO (6% dos FPs, n=4):
   - Pessoa agachada/parada na pilha levando objeto DA PILHA PARA carroca,
     bolsa pessoal ou sacola propria
   - Vocabulario: "vasculhando o lixo", "mexendo no lixo"
   - REGRA: fluxo material da pilha->carroca/sacola = COLETA informal, false.
   - EXCECAO: se DEPOIS de vasculhar a pessoa DEIXAR algo novo no chao,
     isso e descarte. Decide pelo fluxo final.

5) SORTING/TROCA ENTRE PESSOAS (2% dos FPs, n=1):
   - Duas pessoas trocando objetos no local sem descartar
   - "Dois homens trocando objetos, parece descarte mas usam o local para [trocar]"
   - REGRA: sem fluxo material->chao = false.

6) POMBOS, VENTO, SOMBRAS (5% dos FPs, n=3):
   - Pombos andando sobre a pilha; saco de papel se mexendo pelo vento;
     sombras mudando entre frames
   - Vocabulario: "pombos andando", "vento movimentando o lixo"
   - REGRA: sem agente humano realizando deposito = false.

7) VEICULO PARADO SEM DESCARGA (3% dos FPs, n=2):
   - Carro/caminhao estacionado sem manuseio de material
   - "Carro apenas estacionou", "caminhao estacionado"
   - "Pessoa apenas estacionou e desceu com uma crianca"
   - REGRA: estacionar sozinho nao e infracao. Precisa de fluxo material para chao.

DISCRIMINADOR PRIMARIO (decidir CON vs REJ):
POSTURA + DIRECAO DO MATERIAL durante o tempo da pessoa relevante na cena.
- INCLINADA/AGACHADA junto a pilha COM saco/objeto que SAI das maos    = CON
- VEICULO/CARROCA com material indo PARA o chao                        = CON
- Maos cheias->vazias durante interacao com pilha                      = CON
- Passando em linha reta com posicoes diferentes entre frames          = REJ
- Vasculhando: material indo DA pilha PARA carroca/sacola pessoal      = REJ
- Coleta municipal: pilha diminuindo + uniformes + caminhao compactador = REJ
- Sem pessoa interagindo com pilha (pombos, vento, sombra)             = REJ

DISCRIMINADOR SECUNDARIO (suporta mas nao decide sozinho):
DELTA DE PILHA. Nesta camera, descartes pedestres frequentemente NAO produzem
delta visivel (volume invisivel na resolucao). NAO use ausencia de crescimento
como evidencia contra descarte. Mas:
- Pilha DIMINUIU significativamente entre frames = sinal de COLETA (=false)
- Pilha CRESCEU visivelmente = sinal positivo de descarte (poda grande, entulho)

UNIFORME NAO E DISCRIMINADOR. Ja confirmamos descarte por pessoa de uniforme
laranja EMLURB e por pessoa em uniforme generico. Decide pela postura e direcao
do material, nunca pelo vestuario.

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000
[y_min, x_min, y_max, x_max]:
- waste_bbox: residuo depositado (quando visivel como objeto distinto)
- offender_bbox: pessoa/veiculo agente do descarte
Quando o material se mistura a pilha existente, waste_bbox pode ser null desde
que offender_bbox identifique o agente.

waste_type: "Lixo domiciliar" (predominante), "Poda" (frequente), "Entulho"
(raro nesta camera), "Plastico" se inequivoco.
offender_detected descreve apenas a capacidade de identificar o autor.
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


DETAIL_PROMPT_V3_IMBIRIBEIRA = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Local: ponto cronico de descarte em Imbiribeira, Recife.
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada (com fluxo MODERADO
de carros), calcadas, veiculos estacionados, infraestrutura municipal fixa
(postes, lixeiras, bollards), PILHA DE LIXO PRE-EXISTENTE em areas conhecidas
(2 zonas neste ponto), iluminacao variavel. A pilha pre-existente e ESPERADA —
sua presenca NAO indica infracao. O que muda e o COMPORTAMENTO HUMANO/VEICULAR
ao redor dela.

PERFIL DOS DESCARTES REAIS NESTA CAMERA (50/50 pedestres+veiculos):
Diferente de outras cameras, aqui ha MIX equilibrado:
- ~50% pedestres com objeto/saco/carrinho (volumes 0,05-1,5 m³)
- ~50% veiculos descarregando (caminhonete, carro, mini caminhao, caminhao baú)
Volumes maiores que cameras vizinhas → a pilha frequentemente CRESCE visivelmente
entre o primeiro e o ultimo frame. Pile-volume-delta E um sinal util aqui.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos no primeiro
   frame (pilhas pre-existentes, postes, lixeiras, veiculos estacionados).
2. CENA: Trânsito (passantes/carros em movimento) ou estatica (veiculo parado,
   pessoa estacionaria)? Em transito puro, infraction_confirmed=false.
3. AGENTE: Identifique o veiculo PARADO mais relevante OU a pessoa que MAIS
   interage com a pilha. Se nenhum dos dois existe, false.
4. FLUXO DE MATERIAL: Direcao do material observado — DE veiculo PARA chao =
   DESCARGA; DE chao PARA caminhao = COLETA.
5. CHECAR ANTI-PADROES: Antes de decidir CON, verifique a lista abaixo. Trânsito
   misto e coleta EMLURB sao as duas maiores fontes de FP aqui.
6. DECISAO: infraction_confirmed=true SO com evidencia clara (criterios abaixo).

PADROES DE DESCARTE REAL NESTA CAMERA (=true):

VEICULAR (50% dos CONs):
A) Caminhonete / mini caminhao / pickup / carro estacionado (mesma posicao em
   2+ frames) AO LADO DA PILHA, com pessoa ESTACIONARIA entre veiculo e chao,
   manuseando material que vai DE dentro do veiculo PARA o chao.
B) Veiculo com cacamba ABERTA/levantada descarregando entulho.
C) Caracteristica chave: carroceria do veiculo de DESCARGA e tipicamente ABERTA
   (caminhonete sem teto, caçamba, baú aberto). Material e VISIVEL durante a
   transferencia.

PEDESTRE (50% dos CONs):
D) Pessoa AGACHADA ou INCLINADA junto a pilha com saco/objeto/grande sacola
   nas maos, em algum frame, e maos vazias/diferentes em outro frame.
E) Pessoa com CARRINHO DE MAO ao lado da pilha, material indo DO carrinho
   PARA chao.
F) Duas pessoas carregando objeto grande JUNTAS e depositando-o no chao
   ou na pilha.
G) Pessoa "descartando conteudo de saco/sacola" sobre a pilha.

DURACAO/PERSISTENCIA:
H) ATENCAO: descarte real pode acontecer em frames TARDIOS da sequencia.
   Existe caso "dois homens mexendo no lixo, mas no final aparece um outro
   homem que realiza um descarte". NAO decida REJ ja no primeiro frame se
   houver mudanca em frames posteriores.

PADROES DE FALSO POSITIVO COMUNS NESTA CAMERA (=false):
Estes sao os 50 falsos positivos historicos que o operador rejeitou aqui:

1) TRANSITO MISTO (34% dos FPs, n=17):
   - Pessoas + carros + motos + ciclistas + onibus passando em LINHA RETA
   - Posicoes MUITO diferentes entre frames (em movimento)
   - Nao param na pilha; cruzam o quadro
   - Vocabulario: "apenas pessoas e veiculos passando", "veiculos passando",
     "pessoas, carros e caminhoes passando e/ou parados", "cachorros andando"
   - Inclui: cachorros andando perto da pilha (ja foi causa de FP)
   - REGRA: posicoes diferentes entre frames + nenhum parado interagindo
     com material = transito, false.

2) CAMINHAO DE COLETA EMLURB (22% dos FPs, n=11):
   - Caminhao COMPACTADOR (carroceria fechada com hopper traseiro elevatorio)
     parado
   - Pessoas (frequentemente uniformizadas) com sacos/vassouras levando
     material DO CHAO PARA o caminhao
   - Pilha DIMINUI ou desaparece
   - Vocabulario: "caminhao realizando a retirada de lixo", "coleta do lixo",
     "lixo sendo recolhido pelo caminhao", "pessoal realizando a limpeza"
   - DISCRIMINADOR vs descarga real:
     * COLETA: caminhao COMPACTADOR com hopper traseiro; fluxo chao->veiculo;
       pilha diminui
     * DESCARGA: caminhonete/pickup/mini caminhao/baú aberto; fluxo veiculo->chao;
       pilha cresce ou aparece material novo no chao
   - REGRA: fluxo material chao->caminhao = COLETA, false.

3) CATADOR VASCULHANDO / CARROCA (10% dos FPs, n=5):
   - Pessoa parada/agachada na pilha levando objeto DA PILHA PARA carroca,
     bolsa pessoal ou sacola propria
   - Vocabulario: "homem vasculhando o lixo", "homem mexendo no lixo",
     "pessoa mexendo na carroca", "homem apenas pegou um papelao do lixo"
   - REGRA: fluxo material pilha->carroca/sacola = COLETA informal, false.

4) VEICULO PARADO SEM DESCARGA (4% dos FPs, n=2):
   - Carros estacionados (rotina), caminhao estacionado sem ninguem manuseando
     material entre veiculo e chao
   - Vocabulario: "apenas carros estacionados", "apenas um caminhao estacionado"
   - REGRA: estacionar sozinho NAO e infracao; precisa de fluxo material.

5) PESSOAS CARREGANDO MAS NAO DESCARTANDO (2% dos FPs, n=1):
   - "Dois homens carregando item grande (nao realizam o descarte)"
   - Pessoa atravessa carregando algo sem parar/largar na pilha
   - REGRA: carregar sem largar = passante, false.

6) CHUVA (4% dos FPs, n=2):
   - Blur, distorcao visual, manchas que parecem material novo
   - Vocabulario: "apenas esta chovendo"
   - REGRA: na ausencia de agente humano clarissimo, chuva = false.

7) CACHORRO / ANIMAL (6% dos FPs, n=3):
   - Cachorro andando perto/sobre a pilha
   - Mexer aparente na pilha por animal
   - REGRA: sem agente humano realizando deposito = false.

8) CONVERSA EM VEICULO PARADO (2% dos FPs, n=1):
   - Pessoa conversando com ocupante de caminhao parado, sem manuseio
   - Vocabulario: "um homem conversando com uma pessoa dentro de um caminhao
     passando"
   - REGRA: conversar nao basta. Precisa de fluxo material.

DISCRIMINADOR PRIMARIO (decidir CON vs REJ):
Para CENAS COM VEICULO PARADO:
- Caminhao COMPACTADOR EMLURB + fluxo chao->veiculo + pilha diminui  = REJ (coleta)
- Caminhonete/pickup/baú/mini caminhao + fluxo veiculo->chao + material  = CON
- Veiculo parado sem ninguem manuseando material entre veiculo e chao = REJ

Para CENAS COM PEDESTRE:
- Agachado/inclinado na pilha com transicao maos cheias->vazias       = CON
- Carrinho de mao com material indo do carrinho para chao             = CON
- Passando em linha reta com posicoes diferentes (mesmo carregando)   = REJ
- Vasculhando: fluxo da pilha para carroca/sacola pessoal             = REJ

Para CENAS SEM HUMANO INTERAGINDO:
- Animais, chuva, sombras, vento, transito apenas                     = REJ

DISCRIMINADOR SECUNDARIO (suporta mas nao decide sozinho):
DELTA DE PILHA. Diferente de outras cameras desta operacao, AQUI o delta E util:
- Pilha CRESCEU visivelmente + material novo no chao = sinal positivo
- Pilha DIMINUIU = sinal de coleta (= false)
- Pilha INALTERADA com pedestre dispositor = ainda pode ser CON (pequena
  sacola pode nao mudar pilha)

UNIFORME NAO E DISCRIMINADOR. Tanto coleta quanto descarga ocorrem com pessoas
uniformizadas. Decide pela direcao do material e tipo de veiculo.

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000
[y_min, x_min, y_max, x_max]:
- waste_bbox: residuo depositado (quando visivel como objeto distinto)
- offender_bbox: pessoa/veiculo agente do descarte
Quando o material se mistura a pilha existente, waste_bbox pode ser null desde
que offender_bbox identifique o agente.

waste_type: "Lixo domiciliar" (predominante), "Entulho" (frequente em descarga
veicular), "Poda" (raro nesta camera), "Plastico" se inequivoco.
offender_detected descreve apenas a capacidade de identificar o autor.
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


SYSTEMS = {"IMBIRIBEIRA": DETAIL_PROMPT_V3_IMBIRIBEIRA,
           "MANGABEIRA": DETAIL_PROMPT_V3_MANGABEIRA}

# === Shared helpers =========================================================

S3 = boto3.client("s3", region_name="sa-east-1")


def resolve_frame(tmp_dir: Path, image_url: str, frame_name: str, device_id: str) -> Path | None:
    target = tmp_dir / "frames" / device_id / frame_name
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


def fetch_events() -> list[dict]:
    """Same query as camp 20 — 52 events (22 REJ + 30 CON) from prod DB."""
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


def sample_n(frames, n: int) -> list[int]:
    if len(frames) <= n:
        return list(range(len(frames)))
    return [int(round(i * (len(frames) - 1) / (n - 1))) for i in range(n)]


def jpeg_bytes(path: Path, max_edge: int = 1280, quality: int = 85) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_edge, max_edge))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


def build_intro(paths: list[Path], frame_names: list[str], cam_id: int) -> str:
    cam_ctx = {
        10: "cam_imbiribeira (Imbiribeira, Recife)",
        11: "cam_mangabeira (Mangabeira, Recife)",
    }
    return (
        f"Voce recebe {len(paths)} frames sequenciais (ordem cronologica, "
        f"primeiro=earliest, ultimo=latest) de uma camera fixa.\n"
        f"Contexto da camera: {cam_ctx.get(cam_id, 'sem contexto')}\n"
        f"Frame names (ordem): {', '.join(frame_names)}\n\n"
        "Analise a sequencia e retorne JSON estruturado (apenas JSON, sem texto "
        "antes ou depois)."
    )


def score_results(results: list[dict]) -> dict:
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


def print_summary(model_label: str, results: list[dict], total_in: int,
                   total_out: int, cost: float) -> None:
    s = score_results(results)
    print()
    print(f"=== {model_label} per-camera prompts — n={s['n']} ===")
    print(f"acc={s['acc']:.2%}  TP={s['tp']} TN={s['tn']} FP={s['fp']} FN={s['fn']}")
    print(f"precision (CON)={s['precision']:.2%}  recall (CON)={s['recall']:.2%}  "
          f"specificity (REJ)={s['specificity']:.2%}")
    print(f"tokens in={total_in:,} out={total_out:,}  cost=${cost:.4f} "
          f"(avg ${cost / max(s['n'], 1):.4f}/event)")

    print("\n=== per-camera ===")
    for cam in (10, 11):
        sub = [r for r in results if r["cam"] == cam]
        if not sub:
            continue
        ss = score_results(sub)
        print(f"  cam_{cam} n={ss['n']}  acc={ss['acc']:.2%}  TP={ss['tp']} "
              f"TN={ss['tn']} FP={ss['fp']} FN={ss['fn']}")
