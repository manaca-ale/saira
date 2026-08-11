#!/usr/bin/env python3
"""Camp 48 — cliente Bedrock Converse para os VLMs de peso aberto.

Por que um módulo local e não `detector_gemini.ModelOverride`: o seam de produção é
amarrado ao SDK do Gemini (`genai.Client`, `types.Part.from_bytes`, `response_schema`).
Generalizá-lo antes de saber se algum candidato presta seria prematuro. Campanhas
20/21/28/42 já usaram boto3 local para Sonnet/Haiku — é o house style.

O que este módulo NÃO faz: prompt, janela, post-gate. Isso vem do worker de produção,
importado pelo runner. Aqui só entra transporte, structured output, uso e preço.
"""
from __future__ import annotations

import copy
import io
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.config import Config

# Sem `BEDROCK_REGION` no ambiente o valor é o mesmo de sempre — nada já medido muda.
# A sonda do Tema 1 troca de pool regional reatribuindo `bc.REGION` e zerando `_client`.
REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
PROFILE = "codex-ops"          # SSO AdministratorAccess, conta 818680680175

# ── Teto de payload do Bedrock Converse (medido 2026-07-30) ──────────────────
# O limite NÃO é contagem de imagens: é o tamanho do corpo da requisição, e é
# UNIFORME nos 5 candidatos testados. Com frames reais 1280x720 (~297 KB):
#     9 frames = 2,65 MB -> OK        10 frames = 2,95 MB -> "Failed to buffer
#                                     the request body"
# 2,65 MB crus em base64 dão 3,53 MB e 2,95 MB dão 3,93 MB => o teto real é um
# corpo de 4 MB. Orçamento seguro de imagem crua, descontando prompt/schema: 2,7 MB.
#
# Isso é 3x MENOR que o teto do Gemini em prod (GEMINI_MAX_PAYLOAD_BYTES=8 MB).
# Consequência: a janela mediana de prod (23 frames x 297 KB = 6,8 MB) NÃO cabe em
# resolução original. As duas saídas honestas são reduzir resolução (análogo direto
# do `media_resolution=low` do Gemini, que o Camp 47 provou não custar recall) ou
# mosaico. Medido na janela cheia de 48 frames:
#     640px q70 -> 2,65 MB (cabe)     mosaico 4x3 em 4 folhas -> 1,79 MB (cabe)
#     854px q72 -> 4,93 MB (estoura)  960px q70 -> 6,05 MB (estoura)
MAX_RAW_BYTES = 2_700_000
LOW_WIDTH = 640
LOW_QUALITY = 70

# ── Registro de modelos ──────────────────────────────────────────────────────
# `cap` = teto de imagens por request, medido em 2026-07-30 com 40 chamadas reais.
# `price` = (USD/1M input, USD/1M output) da tarifa STANDARD on-demand, puxada da
# AWS Pricing API em us-east-1. O tier `flex` custa ~metade, mas não usamos porque
# a latência deixaria de ser comparável com prod.
@dataclass(frozen=True)
class ModelSpec:
    alias: str
    model_id: str
    cap: Optional[int]          # None = sem teto conhecido
    price: tuple[float, float]
    open_weights: bool
    note: str = ""


MODELS: dict[str, ModelSpec] = {m.alias: m for m in [
    # Aceitam a janela de 48 frames inteira e acertaram a ordenação temporal
    ModelSpec("gemma-3-27b",     "google.gemma-3-27b-it",        48,  (0.23, 0.38), True),
    ModelSpec("gemma-3-12b",     "google.gemma-3-12b-it",        48,  (0.09, 0.29), True),
    ModelSpec("gemma-3-4b",      "google.gemma-3-4b-it",         48,  (0.04, 0.08), True),
    ModelSpec("qwen3-vl-235b",   "qwen.qwen3-vl-235b-a22b",      48,  (0.53, 2.66), True),
    ModelSpec("nemotron-nano-12b", "nvidia.nemotron-nano-12b-v2", 48, (0.06, 0.23), True),
    ModelSpec("kimi-k2.5",       "moonshotai.kimi-k2.5",         48,  (0.60, 3.00), True),
    ModelSpec("magistral-small", "mistral.magistral-small-2509", 48,  (0.50, 1.50), True),
    ModelSpec("ministral-3-14b", "mistral.ministral-3-14b-instruct", 48, (0.20, 0.20), True),
    # Teto baixo: só gate (5) ou mosaico (4 imagens)
    ModelSpec("palmyra-vision-7b", "writer.palmyra-vision-7b",    5,  (0.15, 0.60), True,
              "teto 5 imagens: 6 -> invalid_request_error"),
    # Caro e com throttle agressivo — condicional
    ModelSpec("pixtral-large", "us.mistral.pixtral-large-2502-v1:0", None, (2.00, 6.00), True,
              "throttle erratico; licenca Mistral Research (pesos nao-comerciais)"),
    # ELIMINADOS pelo probe: teto de 3 imagens não roda nem o gate de 5 frames
    ModelSpec("llama4-scout", "us.meta.llama4-scout-17b-instruct-v1:0", 3, (0.17, 0.66), True,
              "ELIMINADO: teto 3 imagens"),
    ModelSpec("llama4-maverick", "us.meta.llama4-maverick-17b-instruct-v1:0", 3, (0.24, 0.97), True,
              "ELIMINADO: teto 3 imagens"),
]}

ELIMINATED = {a for a, m in MODELS.items() if m.note.startswith("ELIMINADO")}

_RETRYABLE = ("ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException",
              "ModelNotReadyException", "InternalServerException", "TooManyRequestsException",
              # botocore: falhas de transporte. Ficaram DE FORA no Camp 49 — o predicado
              # casa por nome, e nenhum destes contém as strings acima, então 9 dos 93
              # erros do qwen voltaram na 1a tentativa, sem backoff. É bug do runner, não
              # incapacidade do modelo. Quem comparar taxa de erro com o Camp 49 tem que
              # recomputar sob o predicado antigo (`_RETRYABLE_CAMP49`) — o JSONL de
              # tentativas guarda a classe de cada falha justamente para isso.
              "ConnectionClosedError", "EndpointConnectionError",
              "ReadTimeoutError", "ConnectTimeoutError")
_RETRYABLE_CAMP49 = _RETRYABLE[:6]

# ── Telemetria por TENTATIVA (desligada por padrão ⇒ zero mudança de comportamento) ──
# Sem isto só dá para medir a taxa de erro POR EVENTO, que depende da política de
# retentativa e portanto não é comparável entre rodadas com políticas diferentes. Com
# isto dá para separar "taxa bruta de 1a tentativa" (propriedade do endpoint) de "taxa
# efetiva por evento" (propriedade do endpoint + do harness).
LOG_ATTEMPTS = False
ATTEMPTS: list[dict] = []
_attempts_lock = threading.Lock()
# Rótulo do trabalho corrente (evento, estágio). Thread-local para que o chamador o
# defina uma vez por job sem que `converse` precise de mais um parâmetro — assim o
# runner do Camp 49 (`bench_bedrock.py`) fica intocado e mesmo assim rende telemetria.
_tls = threading.local()


def set_tag(tag: str) -> None:
    _tls.tag = tag


def _log_attempt(**kw) -> None:
    if not LOG_ATTEMPTS:
        return
    kw["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
    kw["region"] = REGION
    kw["tag"] = getattr(_tls, "tag", "")
    with _attempts_lock:
        ATTEMPTS.append(kw)

_client = None
# Modo de structured output descoberto por modelo: "tool" ou "text".
# Descobrir uma vez e cachear evita pagar uma ValidationException por chamada.
_json_mode: dict[str, str] = {}
# Custo das chamadas gastas descobrindo o modo de structured output de cada modelo
# (uma por modelo). Contabilizado à parte para não poluir o custo/evento.
_discovery_cost: dict[str, float] = {}
# Teto de max_tokens por modelo, aprendido do erro "exceeds the model limit of N".
# palmyra-vision-7b para em 4096; pedir 8192 dava ValidationException em 100% das
# chamadas — era bug do runner, não incapacidade do modelo.
_max_out: dict[str, int] = {}
# Modelos que NÃO aceitam bloco `system` (palmyra-vision-7b devolve
# "Conversation roles must alternate user/assistant/..."). Para esses, o system
# prompt vai dobrado no início da mensagem do usuário.
_no_system: dict[str, bool] = {}


def client():
    global _client
    if _client is None:
        sess = boto3.Session(profile_name=PROFILE, region_name=REGION)
        _client = sess.client(
            "bedrock-runtime",
            config=Config(retries={"max_attempts": 3, "mode": "adaptive"},
                          read_timeout=300, connect_timeout=20),
        )
    return _client


# ── JSON Schema a partir do contrato Pydantic de produção ────────────────────
def tool_schema(schema_cls) -> dict:
    """Converte o modelo Pydantic de prod em JSON Schema aceitável pelo toolConfig.

    A ORDEM DOS CAMPOS é preservada de propósito: `baseline_description` primeiro e
    `scene_delta_analysis` último são Chain-of-Verification deliberado
    (schemas_gemini.py:25,166) — reordenar muda o comportamento do modelo.
    """
    raw = schema_cls.model_json_schema()
    props, required = {}, []
    for name, spec in raw.get("properties", {}).items():
        props[name] = _flatten(copy.deepcopy(spec))
        if name in raw.get("required", []):
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def _flatten(spec: dict) -> dict:
    """Optional[X] do Pydantic vira anyOf[X, null]; vários modelos do Bedrock
    engasgam nisso. Achata para o tipo concreto (o campo já é opcional por não
    estar em `required`)."""
    if "anyOf" in spec:
        opts = [o for o in spec.pop("anyOf") if o.get("type") != "null"]
        if opts:
            merged = opts[0]
            for k, v in merged.items():
                spec.setdefault(k, v)
    for k in ("default", "title", "exclusiveMinimum", "exclusiveMaximum"):
        spec.pop(k, None)
    if "items" in spec and isinstance(spec["items"], dict):
        spec["items"] = _flatten(spec["items"])
    return spec


def _schema_as_text(schema: dict) -> str:
    """Instrução de schema para o fallback JSON-em-texto."""
    lines = []
    for name, spec in schema["properties"].items():
        t = spec.get("type", "string")
        bits = [t]
        if "maxLength" in spec:
            bits.append(f"max {spec['maxLength']} chars")
        if "minimum" in spec or "maximum" in spec:
            bits.append(f"{spec.get('minimum', '')}..{spec.get('maximum', '')}")
        req = "REQUIRED" if name in schema["required"] else "optional"
        desc = (spec.get("description") or "").strip()
        lines.append(f'  "{name}": {"|".join(bits)}  ({req}){" — " + desc if desc else ""}')
    return ("Responda com APENAS um objeto JSON, sem markdown, sem cercas de código, "
            "com exatamente estas chaves NESTA ORDEM:\n{\n" + "\n".join(lines) + "\n}")


# ── payload ──────────────────────────────────────────────────────────────────
def _image_blocks(blobs: list[bytes]) -> list[dict]:
    return [{"image": {"format": "jpeg", "source": {"bytes": b}}} for b in blobs]


def _downscale(path: Path, width: int, quality: int) -> bytes:
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > width:
            im = im.resize((width, max(1, round(im.height * width / im.width))))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        return buf.getvalue()


def _even_drop(items: list, k: int) -> list:
    """Sub-amostra preservando primeiro e último — mesma matemática de
    `event_windows.subsample_frames` (event_windows.py:157)."""
    n = len(items)
    if n <= k or k < 2:
        return items[:max(1, k)]
    step = (n - 1) / (k - 1)
    return [items[i] for i in sorted({round(i * step) for i in range(k)})]


@dataclass
class Payload:
    blobs: list[bytes]
    mode: str                  # orig | low
    n_images: int
    raw_bytes: int
    n_dropped: int = 0         # frames cortados para caber no teto do Bedrock


def prepare_images(paths: list[Path], mode: str = "orig",
                   budget: int = MAX_RAW_BYTES) -> Payload:
    """Codifica os frames respeitando o teto de corpo do Bedrock.

    `mode="orig"` manda os bytes do disco (paridade com o que prod manda ao Gemini);
    `mode="low"` reduz para 640px q70 (análogo do `media_resolution=low`).
    Se ainda estourar, corta frames uniformemente — e REGISTRA quantos, porque um
    corte silencioso viraria "sub-amostrei sem contar", exatamente o erro que
    invalidou os camps 20/21.
    """
    if mode == "low":
        blobs = [_downscale(p, LOW_WIDTH, LOW_QUALITY) for p in paths]
    else:
        blobs = [p.read_bytes() for p in paths]
    total = sum(len(b) for b in blobs)
    dropped = 0
    if total > budget and len(blobs) > 1:
        # regra de três no tamanho médio, depois confirma e vai apertando
        k = max(1, int(len(blobs) * budget / total))
        while k >= 1:
            cand = _even_drop(blobs, k)
            if sum(len(b) for b in cand) <= budget or k == 1:
                dropped = len(blobs) - len(cand)
                blobs = cand
                break
            k -= 1
        total = sum(len(b) for b in blobs)
    return Payload(blobs=blobs, mode=mode, n_images=len(blobs),
                   raw_bytes=total, n_dropped=dropped)


@dataclass
class BedrockResult:
    report: Any = None                 # instância do modelo Pydantic, ou None
    raw_text: str = ""
    json_valid: bool = False
    json_mode: str = ""
    tok_in: int = 0
    tok_out: int = 0
    tok_cache_read: int = 0
    latency_ms: int = 0
    n_images: int = 0
    cost_usd: float = 0.0
    error: str = ""
    stop_reason: str = ""


def cost(alias: str, tok_in: int, tok_out: int) -> float:
    """Custo estimado. Modelos de raciocínio (magistral/nemotron/kimi) emitem o
    reasoning como bloco de output, então `outputTokens` do Bedrock JÁ inclui o
    pensamento — diferente do Gemini, onde `thoughts_token_count` vem separado e
    omiti-lo subestimava ~2x o custo (bug do Camp 47)."""
    pin, pout = MODELS[alias].price
    return tok_in / 1e6 * pin + tok_out / 1e6 * pout


def _extract(resp) -> tuple[str, Optional[dict]]:
    """(texto concatenado, input do toolUse se houver)."""
    texts, tool_in = [], None
    for block in resp.get("output", {}).get("message", {}).get("content", []):
        if "text" in block:
            texts.append(block["text"])
        elif "toolUse" in block:
            tool_in = block["toolUse"].get("input")
        elif "reasoningContent" in block:
            rc = block["reasoningContent"].get("reasoningText", {}).get("text", "")
            if rc:
                texts.append(f"<reasoning>{rc}</reasoning>")
    return "\n".join(texts), tool_in


_JSON_RE = re.compile(r"\{.*\}", re.S)


def _json_from_text(text: str) -> Optional[dict]:
    """Extrai o maior objeto JSON do texto, tolerando cercas de código e
    preâmbulo/raciocínio ao redor."""
    t = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.S)
    t = re.sub(r"```(?:json)?", "", t)
    m = _JSON_RE.search(t)
    if not m:
        return None
    for cand in (m.group(0), m.group(0).rstrip().rstrip(",") + "}"):
        try:
            v = json.loads(cand)
            if isinstance(v, dict):
                return v
        except Exception:
            continue
    return None


def converse(alias: str, system: str, user: str, images: list[bytes],
             schema_cls, max_tokens: int = 8192, temperature: float = 0.0,
             timeout_tries: int = 5, force_mode: Optional[str] = None) -> BedrockResult:
    """Uma chamada Converse com imagens + structured output.

    Tenta `toolConfig` com `toolChoice` forçado (equivalente ao `response_schema` do
    Gemini). Se o modelo rejeitar tool-use, cai para JSON-em-texto e memoriza o modo.
    O parse usa `_parse_report_lenient` do worker de prod, que clipa strings longas e
    revalida — nunca descarta uma detecção por erro cosmético de schema.
    """
    import worker.detector_gemini as dg   # importado aqui: runner já ajustou sys.path

    spec = MODELS[alias]
    res = BedrockResult(n_images=len(images))
    if spec.cap is not None and len(images) > spec.cap:
        res.error = f"cap: {len(images)} imagens > teto {spec.cap} de {alias}"
        return res
    raw = sum(len(b) for b in images)
    if raw > MAX_RAW_BYTES:
        res.error = f"payload: {raw/1e6:.2f} MB > teto {MAX_RAW_BYTES/1e6:.2f} MB"
        return res

    schema = tool_schema(schema_cls)
    mode = force_mode or _json_mode.get(alias, "tool")
    content = _image_blocks(images)
    started = time.monotonic()

    for attempt in range(1, timeout_tries + 1):
        body: dict = {
            "modelId": spec.model_id,
            "messages": [{"role": "user", "content": content + [{"text": user}]}],
            "inferenceConfig": {"maxTokens": min(max_tokens, _max_out.get(alias, max_tokens)),
                                "temperature": temperature},
        }
        sys_txt = system if mode == "tool" else system + "\n\n" + _schema_as_text(schema)
        if _no_system.get(alias, False):
            # sem bloco `system`: dobra a instrução no início da mensagem do usuário
            body["messages"][0]["content"][-1]["text"] = sys_txt + "\n\n" + user
        else:
            body["system"] = [{"text": sys_txt}]
        if mode == "tool":
            body["toolConfig"] = {
                "tools": [{"toolSpec": {
                    "name": "report",
                    "description": "Structured analysis result.",
                    "inputSchema": {"json": schema},
                }}],
                "toolChoice": {"tool": {"name": "report"}},
            }
        t_att = time.monotonic()
        try:
            resp = client().converse(**body)
        except Exception as exc:
            name = type(exc).__name__
            msg = str(exc)
            att_ms = int((time.monotonic() - t_att) * 1000)
            retryable = any(t in name or t in msg for t in _RETRYABLE)
            _log_attempt(alias=alias, model_id=spec.model_id, attempt=attempt,
                         n_images=len(images), raw_bytes=raw, ok=False, exc=name,
                         msg=msg[:160], latency_ms=att_ms, retryable=retryable,
                         retryable_camp49=any(t in name or t in msg
                                              for t in _RETRYABLE_CAMP49))
            # tool-use não suportado -> degrada para texto e recomeça (não conta tentativa)
            if mode == "tool" and ("toolConfig" in msg or "tool" in msg.lower()) and \
                    "Validation" in name:
                _json_mode[alias] = mode = "text"
                continue
            if "roles must alternate" in msg and not _no_system.get(alias):
                _no_system[alias] = True
                continue
            m_lim = re.search(r"exceeds the model limit of (\d+)", msg)
            if m_lim:
                _max_out[alias] = int(m_lim.group(1))
                continue
            if retryable and attempt < timeout_tries:
                time.sleep(min(90, 6 * 2 ** (attempt - 1)) * (0.7 + 0.6 * random.random()))
                continue
            res.error = f"{name}: {msg[:200]}"
            res.latency_ms = int((time.monotonic() - started) * 1000)
            return res

        _log_attempt(alias=alias, model_id=spec.model_id, attempt=attempt,
                     n_images=len(images), raw_bytes=raw, ok=True, exc="",
                     latency_ms=int((time.monotonic() - t_att) * 1000),
                     tok_in=int((resp.get("usage") or {}).get("inputTokens", 0) or 0),
                     tok_out=int((resp.get("usage") or {}).get("outputTokens", 0) or 0))
        res.latency_ms = int((time.monotonic() - started) * 1000)
        res.stop_reason = resp.get("stopReason", "")
        u = resp.get("usage", {}) or {}
        res.tok_in = int(u.get("inputTokens", 0) or 0)
        res.tok_out = int(u.get("outputTokens", 0) or 0)
        res.tok_cache_read = int(u.get("cacheReadInputTokens", 0) or 0)
        res.cost_usd = cost(alias, res.tok_in, res.tok_out)

        text, tool_in = _extract(resp)
        # Vários modelos open-weight ACEITAM o toolConfig sem erro e simplesmente
        # NÃO chamam a tool — respondem texto livre e inventam os nomes dos campos
        # (gemma-3-27b devolveu "confidence" em vez de "confidence_0_100" e ecoou o
        # contexto da câmera como campos). Silenciosamente inaceitável: degrada para
        # o modo texto, que carrega a lista literal de chaves, e refaz uma vez.
        if mode == "tool" and tool_in is None and _json_mode.get(alias) != "text":
            _json_mode[alias] = mode = "text"
            res.tok_in += res.tok_in and 0  # o gasto da descoberta fica registrado abaixo
            _discovery_cost[alias] = _discovery_cost.get(alias, 0.0) + \
                cost(alias, int((resp.get("usage") or {}).get("inputTokens", 0) or 0),
                     int((resp.get("usage") or {}).get("outputTokens", 0) or 0))
            continue
        _json_mode.setdefault(alias, mode)
        res.json_mode = mode
        res.raw_text = json.dumps(tool_in, ensure_ascii=False) if tool_in else text
        payload = tool_in if isinstance(tool_in, dict) else _json_from_text(text)
        if payload is None:
            res.error = f"sem JSON na resposta (stop={res.stop_reason})"
            return res
        try:
            # mesmo parse leniente de prod (detector_gemini:746)
            res.report = dg._parse_report_lenient(
                schema_cls, json.dumps(payload, ensure_ascii=False))
            res.json_valid = True
        except Exception as exc:
            res.error = f"schema: {type(exc).__name__}: {str(exc)[:160]}"
        return res

    res.error = "esgotou as tentativas"
    res.latency_ms = int((time.monotonic() - started) * 1000)
    return res
