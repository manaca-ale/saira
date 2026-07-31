"""Cliente AWS Bedrock Converse — usado APENAS pelo shadow log-only (Camp 49).

Porte de `benchmarks/campaigns/49-picam001-open-weight-tuning-2026-07-31/scripts/
_bedrock_client.py`, que mediu `kimi-k2.5` em chamada única batendo a produção em recall
(19/19 vs 17/19) a −9% de custo. Nada aqui toca o caminho Gemini de produção.

Cinco desvios deliberados em relação ao módulo do bench:

1. **Sem perfil SSO.** O bench usa `boto3.Session(profile_name="codex-ops")`; em container
   não há perfil — as credenciais vêm do ambiente. Segue o idioma de
   `storage_s3._get_s3_client`: região sempre, credenciais explícitas só se configuradas.
2. **cv2 em vez de PIL.** O worker não tem Pillow; tem `opencv-python-headless`. O
   idioma de encode com qualidade é o de `mosaic.py`.
3. **Guardrails de latência.** O shadow roda INLINE na thread serial do pipeline, e o
   incidente de 23/07 (guardrails G2-G5) foi backlog por chamada lenta. O bench tolera
   `min(90, 6*2^n)` de sleep por até 5 tentativas — minutos bloqueando a fila. Aqui há
   teto de backoff, poucas tentativas e um **deadline absoluto de wall-clock**.
4. **`force_mode`** exposto: o kimi aceita `toolConfig` e o IGNORA, caindo no ramo de
   degradação silenciosa — que queima uma chamada por processo. Forçar `"text"` evita.
5. Import relativo de `detector_gemini` (reusa `_parse_report_lenient`, o mesmo parse
   leniente de produção).
"""
from __future__ import annotations

import copy
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2

from . import config
from . import detector_gemini as dg

logger = logging.getLogger(__name__)

# Teto de payload do Bedrock Converse (medido no Camp 48/49): o limite não é contagem de
# imagens, é o corpo da requisição (~4 MB). Descontando prompt/schema, o orçamento seguro
# de imagem crua é 2,7 MB — 3x menor que o teto do Gemini em prod (8 MB). Daí a janela
# cheia de 48 frames só caber em resolução reduzida.
MAX_RAW_BYTES = 2_700_000


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    model_id: str
    cap: Optional[int]          # teto de imagens por request (None = sem teto conhecido)
    price: tuple[float, float]  # (USD/1M input, USD/1M output) on-demand standard
    note: str = ""


# Só os candidatos que sobreviveram ao Camp 49 com 0 erros em ~1.500 chamadas. Os demais
# (qwen, nemotron, palmyra, llama4) ficaram de fora: indisponibilidade de endpoint ou
# teto de imagens baixo demais para a janela desta câmera.
MODELS: dict[str, ModelSpec] = {m.alias: m for m in [
    ModelSpec("kimi-k2.5", "moonshotai.kimi-k2.5", 48, (0.60, 3.00)),
    ModelSpec("magistral-small", "mistral.magistral-small-2509", 48, (0.50, 1.50)),
]}

_RETRYABLE = ("ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException",
              "ModelNotReadyException", "InternalServerException", "TooManyRequestsException")

_client = None
# Modo de structured output por modelo ("tool" ou "text"), descoberto uma vez e cacheado.
_json_mode: dict[str, str] = {}
# Teto de max_tokens aprendido do erro "exceeds the model limit of N".
_max_out: dict[str, int] = {}
# Modelos que não aceitam bloco `system` — nesses, o system vai no início do user.
_no_system: dict[str, bool] = {}


def client():
    """Cliente bedrock-runtime. Credenciais do ambiente (mesmo idioma do storage_s3)."""
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        kwargs: dict[str, Any] = {"region_name": config.SHADOW_BEDROCK_REGION}
        if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = config.AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = config.AWS_SECRET_ACCESS_KEY
        # Retentativa do botocore DESLIGADA: a nossa é explícita e checa o deadline. Com
        # as duas ligadas o pior caso multiplica e trava a thread serial do pipeline.
        kwargs["config"] = Config(
            retries={"max_attempts": 1, "mode": "standard"},
            read_timeout=max(10, config.SHADOW_BEDROCK_DEADLINE_S),
            connect_timeout=10,
        )
        _client = boto3.client("bedrock-runtime", **kwargs)
    return _client


def reset_client() -> None:
    """Descarta o cliente cacheado (usado pelos testes)."""
    global _client
    _client = None


# ── JSON Schema a partir do contrato Pydantic de produção ────────────────────
def tool_schema(schema_cls) -> dict:
    """Converte o modelo Pydantic de prod em JSON Schema aceitável pelo toolConfig.

    A ORDEM DOS CAMPOS é preservada de propósito: `baseline_description` primeiro é
    Chain-of-Verification deliberado (schemas_gemini.py) — reordenar muda o
    comportamento do modelo.
    """
    raw = schema_cls.model_json_schema()
    props, required = {}, []
    for name, spec in raw.get("properties", {}).items():
        props[name] = _flatten(copy.deepcopy(spec))
        if name in raw.get("required", []):
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def _flatten(spec: dict) -> dict:
    """Optional[X] do Pydantic vira anyOf[X, null] e vários modelos do Bedrock engasgam.
    Achata para o tipo concreto (o campo já é opcional por não estar em `required`)."""
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
    """Instrução de schema para o modo JSON-em-texto."""
    lines = []
    for name, spec in schema["properties"].items():
        bits = [spec.get("type", "string")]
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
    """Reduz para `width` px e reencoda em JPEG. cv2 porque o worker não tem Pillow."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise OSError(f"não consegui ler o frame: {path}")
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, max(1, round(h * width / w))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise OSError(f"falha ao codificar JPEG: {path}")
    return buf.tobytes()


def _even_drop(items: list, k: int) -> list:
    """Sub-amostra preservando primeiro e último — mesma matemática de
    `event_windows.subsample_frames`."""
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


def prepare_images(paths: list[Path], mode: str = "low", budget: Optional[int] = None,
                   width: Optional[int] = None, quality: Optional[int] = None) -> Payload:
    """Codifica os frames respeitando o teto de corpo do Bedrock.

    `mode="orig"` manda os bytes do disco; `mode="low"` reduz (análogo do
    `media_resolution=low` do Gemini). Se ainda estourar, corta frames uniformemente — e
    REGISTRA quantos, porque um corte silencioso viraria "sub-amostrei sem contar",
    exatamente o erro que invalidou os camps 20/21.
    """
    budget = MAX_RAW_BYTES if budget is None else budget
    if mode == "low":
        w = config.SHADOW_BEDROCK_IMG_WIDTH if width is None else width
        q = config.SHADOW_BEDROCK_IMG_QUALITY if quality is None else quality
        blobs = [_downscale(p, w, q) for p in paths]
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
    latency_ms: int = 0
    n_images: int = 0
    cost_usd: float = 0.0
    error: str = ""
    stop_reason: str = ""


def cost(alias: str, tok_in: int, tok_out: int) -> float:
    """Modelos de raciocínio (kimi/magistral) emitem o reasoning como bloco de output, então
    `outputTokens` do Bedrock JÁ inclui o pensamento — diferente do Gemini, onde
    `thoughts_token_count` vem separado e omiti-lo subestimava ~2x o custo (bug do Camp 47)."""
    spec = MODELS.get(alias)
    if spec is None:
        return 0.0
    pin, pout = spec.price
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
    """Extrai o maior objeto JSON do texto, tolerando cercas de código e raciocínio ao redor."""
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
        except json.JSONDecodeError:
            continue
    return None


def converse(alias: str, system: str, user: str, images: list[bytes], schema_cls,
             max_tokens: int = 8192, temperature: float = 0.0,
             timeout_tries: Optional[int] = None, force_mode: Optional[str] = None,
             deadline_s: Optional[int] = None) -> BedrockResult:
    """Uma chamada Converse com imagens + structured output. NUNCA levanta.

    Tenta `toolConfig` com `toolChoice` forçado (equivalente ao `response_schema` do
    Gemini); se o modelo rejeitar ou ignorar tool-use, cai para JSON-em-texto e memoriza
    o modo. O parse usa `_parse_report_lenient` de produção, que clipa strings longas e
    revalida — nunca descarta por erro cosmético de schema.

    O `deadline_s` é um teto de wall-clock para a chamada INTEIRA (todas as tentativas):
    esta função roda na thread serial do pipeline e não pode virar backlog.
    """
    tries = config.SHADOW_BEDROCK_TIMEOUT_TRIES if timeout_tries is None else timeout_tries
    deadline_s = config.SHADOW_BEDROCK_DEADLINE_S if deadline_s is None else deadline_s

    spec = MODELS.get(alias)
    res = BedrockResult(n_images=len(images))
    if spec is None:
        res.error = f"alias desconhecido: {alias!r} (conhecidos: {sorted(MODELS)})"
        return res
    if spec.cap is not None and len(images) > spec.cap:
        res.error = f"cap: {len(images)} imagens > teto {spec.cap} de {alias}"
        return res
    raw = sum(len(b) for b in images)
    if raw > MAX_RAW_BYTES:
        res.error = f"payload: {raw / 1e6:.2f} MB > teto {MAX_RAW_BYTES / 1e6:.2f} MB"
        return res

    schema = tool_schema(schema_cls)
    mode = force_mode or _json_mode.get(alias, "tool")
    content = _image_blocks(images)
    started = time.monotonic()
    deadline = started + max(1, deadline_s)

    def _elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    attempt = 0
    while attempt < tries:
        attempt += 1
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
        try:
            resp = client().converse(**body)
        except Exception as exc:  # noqa: BLE001 — o shadow nunca pode derrubar prod
            name = type(exc).__name__
            msg = str(exc)
            # Ajustes de compatibilidade: não contam tentativa, mas respeitam o deadline.
            adjusted = False
            if mode == "tool" and "Validation" in name and "tool" in msg.lower():
                _json_mode[alias] = mode = "text"
                adjusted = True
            elif "roles must alternate" in msg and not _no_system.get(alias):
                _no_system[alias] = True
                adjusted = True
            else:
                m_lim = re.search(r"exceeds the model limit of (\d+)", msg)
                if m_lim:
                    _max_out[alias] = int(m_lim.group(1))
                    adjusted = True
            if adjusted:
                attempt -= 1
                if time.monotonic() < deadline:
                    continue
                res.error = f"deadline ({deadline_s}s) ao ajustar: {name}"
                res.latency_ms = _elapsed_ms()
                return res
            if any(t in name or t in msg for t in _RETRYABLE) and attempt < tries:
                backoff = min(config.SHADOW_BEDROCK_BACKOFF_CAP_S, 2 * 2 ** (attempt - 1))
                backoff *= 0.7 + 0.6 * random.random()
                if time.monotonic() + backoff < deadline:
                    time.sleep(backoff)
                    continue
                res.error = f"deadline ({deadline_s}s) após {name}"
                res.latency_ms = _elapsed_ms()
                return res
            res.error = f"{name}: {msg[:200]}"
            res.latency_ms = _elapsed_ms()
            return res

        res.latency_ms = _elapsed_ms()
        res.stop_reason = resp.get("stopReason", "")
        u = resp.get("usage", {}) or {}
        res.tok_in = int(u.get("inputTokens", 0) or 0)
        res.tok_out = int(u.get("outputTokens", 0) or 0)
        res.cost_usd = cost(alias, res.tok_in, res.tok_out)

        text, tool_in = _extract(resp)
        # Vários open-weight ACEITAM o toolConfig sem erro e simplesmente NÃO chamam a
        # tool — respondem texto livre inventando nomes de campo. Degrada para o modo
        # texto (que carrega a lista literal de chaves) e refaz uma vez. Passar
        # force_mode="text" evita pagar essa descoberta.
        if mode == "tool" and tool_in is None and _json_mode.get(alias) != "text":
            _json_mode[alias] = mode = "text"
            logger.info("bedrock: %s ignorou toolConfig — degradando para JSON-em-texto", alias)
            attempt -= 1
            if time.monotonic() < deadline:
                continue
            res.error = f"deadline ({deadline_s}s) ao degradar para texto"
            return res
        _json_mode.setdefault(alias, mode)
        res.json_mode = mode
        res.raw_text = json.dumps(tool_in, ensure_ascii=False) if tool_in else text
        payload = tool_in if isinstance(tool_in, dict) else _json_from_text(text)
        if payload is None:
            res.error = f"sem JSON na resposta (stop={res.stop_reason})"
            return res
        try:
            # mesmo parse leniente de prod
            res.report = dg._parse_report_lenient(
                schema_cls, json.dumps(payload, ensure_ascii=False))
            res.json_valid = True
        except Exception as exc:  # noqa: BLE001
            res.error = f"schema: {type(exc).__name__}: {str(exc)[:160]}"
        return res

    res.error = f"esgotou as {tries} tentativas"
    res.latency_ms = _elapsed_ms()
    return res
