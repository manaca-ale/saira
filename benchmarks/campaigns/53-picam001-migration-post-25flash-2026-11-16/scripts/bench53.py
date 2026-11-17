#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 53 — pi-cam-001: migracao pos gemini-2.5-flash (roteado para 3.5-flash-lite em 01/12/2026).

Roda a cascata REAL do worker (gate Agent-1 -> detail Agent-2) sobre o dataset oficial
`cam_picam001`, por EVENTO, em ESTAGIOS SEPARADOS com cache em disco:

  gate    uma chamada de gate por evento            -> results/gate__<braco>__r<rep>.jsonl
  detail  uma chamada de detail por evento escolhido -> results/detail__<braco>__r<rep>.jsonl
  score   combina um arquivo de gate com um de detail (offline, sem custo)

Motivo dos estagios: o gate de producao (2.5-flash-lite) NAO muda entre os candidatos de
detail, e o orcamento da semana e curto. Rodar o gate uma vez e so o detail por candidato
isola o efeito do detail e corta o custo. O gate nao e deterministico entre dias (camp 51),
por isso ha `--rep` e o detail roda na UNIAO dos eventos que passaram em algum gate.

PARIDADE (caminho event-driven, igual a camps 47/49, que espelham main._run_gemini_cascade):
  janela  = sorted(frames) -> event_windows.subsample_frames(., 48)
                           -> event_windows.fit_frames_to_payload(., 8_000_000)
  gate    = analyze_new_litter_with_gemini(first=win[0], last=win[-1], 3 mids uniformes)
  dispara = new_litter_detected and confidence_0_100 >= 85
  detail  = analyze_with_gemini(image_paths=win)
  modelos alternativos entram pelo `ModelOverride` do proprio worker (mesmo pos-processamento).

DESVIOS CONHECIDOS (ver run-config.yaml): first=win[0] (prod pode usar o ultimo frame da
janela anterior), prior_window_context=None, sem BGSUB, sem re-vote, max_output_tokens=8192,
auth por token do gcloud em vez de ADC. Thinking do gate = 2048 (prod, conferido na camp 52;
as camps 47/49 usaram 1024).

Uso:
  python bench53.py list
  python bench53.py gate   --arm g25l_v1 --rep 1 --dry-run
  python bench53.py gate   --arm g25l_v1 --rep 1 --max-usd 0.30
  python bench53.py detail --arm d25f_v1 --rep 1 --events-from g25l_v1:1 --max-usd 1.20
  python bench53.py score  --gate g25l_v1:1 --detail d25f_v1:1
  python bench53.py probe  --arm d35l_v1_routed --n 2      # mede tokens reais em 2 eventos
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

warnings.filterwarnings("ignore")
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
CAMP = HERE.parent
REPO = HERE.parents[3]
DATASET = Path(os.environ.get("SAIRA_DATASET_ROOT", r"C:\Saira\data\datasets\official"))
CAM = DATASET / "cam_picam001"
RESULTS = CAMP / "results"
RESULTS.mkdir(exist_ok=True)
CAMPAIGN = "53"

GCP_PROJECT = os.environ.get("BENCH_GCP_PROJECT", "saira-tests-260520")   # conta "Saira - Testes"
GCP_LOCATION = os.environ.get("BENCH_GCP_LOCATION", "global")
GCLOUD_ACCOUNT = os.environ.get("BENCH_GCLOUD_ACCOUNT", "")               # vazio = conta ativa

# ── env de paridade, ANTES de importar worker.config ─────────────────────────
os.environ["GEMINI_CASCADE_MAX_FRAMES"] = "48"
os.environ["GEMINI_MAX_PAYLOAD_BYTES"] = "8000000"
os.environ["GEMINI_GATE_MID_FRAMES"] = "3"
os.environ["GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE"] = "85"
os.environ["GEMINI_AGENT1_THINKING_BUDGET"] = "2048"
os.environ["GEMINI_MAX_OUTPUT_TOKENS"] = "8192"
os.environ["GEMINI_AGENT1_MAX_OUTPUT_TOKENS"] = "8192"
# Timeout do cliente: o worker "desiste" da chamada mas ESPERA ela terminar (o `with
# ThreadPoolExecutor` faz shutdown(wait=True)) e depois tenta de novo — a chamada lenta e
# paga duas ou tres vezes. Em 16/11/2026 o detail no 2.5-flash levou 17 a 46 s com janelas de
# 17 a 32 frames (era 15 s em julho); com 60 s havia retries pagos. Producao usa 30 s (default).
os.environ["GEMINI_TIMEOUT_SECONDS"] = os.environ.get("BENCH_TIMEOUT_S", "180")
os.environ["GEMINI_AGENT1_TIMEOUT_SECONDS"] = os.environ.get("BENCH_TIMEOUT_S", "180")
os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
os.environ["GEMINI_AGENT1_MODEL"] = "gemini-2.5-flash-lite"
os.environ["GEMINI_USE_VERTEX"] = "true"
os.environ["GCP_PROJECT"] = GCP_PROJECT
os.environ["GCP_LOCATION"] = GCP_LOCATION
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")

sys.path.insert(0, str(REPO / "services" / "yolo-worker-vm" / "src"))
sys.path.insert(0, str(REPO / "benchmarks" / "scripts"))
sys.path.insert(0, str(REPO / "benchmarks" / "campaigns"
                       / "49-picam001-open-weight-tuning-2026-07-31" / "scripts"))

import worker.config as cfg                      # noqa: E402
import worker.event_windows as event_windows     # noqa: E402
import worker.detector_gemini as dg              # noqa: E402
import _prompts_v4picam as p_v4                  # noqa: E402  (camp 49)
from bench_budget import Budget, BudgetExceeded, cost_usd  # noqa: E402

CAMERA_ROW = {"name": "Residencial Via Mangue III - 2", "device_id": "pi-cam-001",
              "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
              "bairro": "Imbiribeira", "rpa": "RPA-1"}
TRIGGER_THR = 85
# Fracao dos eventos da pi-cam-001 que passa no gate EM PRODUCAO (no dataset passa ~metade,
# porque ele so tem eventos que viraram deteccao + 40 cenas vazias). Derivada do custo medido
# em producao (US$ 0,00135/evento, 28/07 a 04/08/2026, 3.988 eventos, validado contra a
# fatura) e dos custos por chamada medidos nesta campanha: 0,00135 = 0,0011 + p * 0,0112
# -> p ~ 2,2%. Confere com a ordem de grandeza das deteccoes do periodo (54 a 90 em 3.988).
P_PASS_PROD = 0.022
_V1_GATE, _V1_DETAIL = dg.NEW_LITTER_SYSTEM_PROMPT, dg.SYSTEM_PROMPT

# ── Bracos ───────────────────────────────────────────────────────────────────
# prompt: v1 (worker), v4 (camp 49, flagrante + catador), g3 (worker/_prompts_g3)
# think : None = o que o worker manda hoje (gate: thinking_budget 2048; detail: nada)
#         "minimal"|"low"|"medium"|"high" = thinking_level (Gemini 3)
# media : None = padrao do modelo; "low"|"medium"|"high" = media_resolution
# frames: None = janela cheia; int = subamostra uniforme (so detail)
# est   : estimativa de custo por chamada (USD), usada na trava antes de rodar
GATE_ARMS = {
    "g25l_v1":  {"model": "gemini-2.5-flash-lite", "prompt": "v1", "think": None, "media": None, "est": 0.0012},
    "g25l_v4":  {"model": "gemini-2.5-flash-lite", "prompt": "v4", "think": None, "media": None, "est": 0.0013},
    "g31l_v4":  {"model": "gemini-3.1-flash-lite", "prompt": "v4", "think": "low", "media": "low", "est": 0.0015},
    "g35l_v4":  {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "minimal", "media": "low", "est": 0.0020},
}
DETAIL_ARMS = {
    # producao hoje
    "d25f_v1": {"model": "gemini-2.5-flash", "prompt": "v1", "think": None, "media": None, "est": 0.014},
    # prompt V4 no modelo de hoje (camp 49: melhor configuracao conhecida)
    "d25f_v4": {"model": "gemini-2.5-flash", "prompt": "v4", "think": None, "media": None, "est": 0.014},
    # o que acontece em 01/12 se ninguem mexer: MESMA requisicao, modelo roteado
    "d35l_v1_routed": {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": None, "media": None, "est": 0.030},
    # candidatos de configuracao no 3.5-flash-lite. Nome: d35l_<prompt>_<media>_<thinking>.
    # media: low=280 tok/frame (perto dos 258 do 2.5), med=560, def=1120 (padrao do modelo).
    # `est` = preco de LISTA por chamada (o runner aplica 50% com --flex).
    # passo 1 (resolucao baixa): separar o efeito do prompt do efeito do thinking
    "d35l_v1_low_min":  {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": "minimal", "media": "low", "est": 0.005},
    "d35l_v1_low_high": {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": "high", "media": "low", "est": 0.011},
    "d35l_v1_med_high": {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": "high", "media": "medium", "est": 0.014},
    "d35l_g3_low_med":  {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "medium", "media": "low", "est": 0.009},
    "d35l_g3_med_high": {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "high", "media": "medium", "est": 0.014},
    "d35l_v4_low_min":  {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "minimal", "media": "low", "est": 0.005},
    "d35l_v4_low_low":  {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "low", "media": "low", "est": 0.008},
    "d35l_v4_low_med":  {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "medium", "media": "low", "est": 0.011},
    "d35l_v4_low_high": {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "high", "media": "low", "est": 0.014},
    "d35l_g3_low_high": {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "high", "media": "low", "est": 0.011},
    "d35l_v1_low_med":  {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": "medium", "media": "low", "est": 0.011},
    # passo 2: mais resolucao no melhor par prompt x thinking
    "d35l_v4_med_med":  {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "medium", "media": "medium", "est": 0.015},
    "d35l_v4_med_high": {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "high", "media": "medium", "est": 0.018},
    "d35l_v4_def_min":  {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": None, "media": None, "est": 0.012},
    "d35l_v4_def_high": {"model": "gemini-3.5-flash-lite", "prompt": "v4", "think": "high", "media": None, "est": 0.024},
    "d35l_v1_def_high": {"model": "gemini-3.5-flash-lite", "prompt": "v1", "think": "high", "media": None, "est": 0.024},
    "d35l_g3_def_high": {"model": "gemini-3.5-flash-lite", "prompt": "g3", "think": "high", "media": None, "est": 0.024},
    # modelo mais forte como detail: teto do que se recupera trocando de modelo. Preco de
    # lista 0,75 / 3,75 hoje e 1,50 / 7,50 a partir de 01/01/2027 (com thinking, passa de +20%).
    "d38f_g3_low_med":  {"model": "gemini-3.8-flash", "prompt": "g3", "think": "medium", "media": "low", "est": 0.020},
    "d38f_v1_low_med":  {"model": "gemini-3.8-flash", "prompt": "v1", "think": "medium", "media": "low", "est": 0.020},
    "d38f_v1_low_min":  {"model": "gemini-3.8-flash", "prompt": "v1", "think": "minimal", "media": "low", "est": 0.010},
    # 3.1-flash-lite como detail (mais barato por token; desliga em 07/05/2027)
    "d31l_v4_low_high": {"model": "gemini-3.1-flash-lite", "prompt": "v4", "think": "high", "media": "low", "est": 0.008},
    "d31l_v4_low_med":  {"model": "gemini-3.1-flash-lite", "prompt": "v4", "think": "medium", "media": "low", "est": 0.007},
}

# ── Auth: token do gcloud (politica da org bloqueia chave de conta de servico) ─
_client = None


def _gcloud_exe() -> str:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        raise RuntimeError("gcloud nao encontrado no PATH")
    return exe


def _mint_token():
    """Token de acesso + validade REAL, pelo `gcloud config config-helper`.

    `gcloud auth print-access-token` devolve o token em cache sem dizer quando vence; a
    primeira versao deste runner assumia 40 min e tomou 401 UNAUTHENTICATED no meio de uma
    execucao (16/11/2026). `--min-expiry=20m` faz o gcloud renovar se faltar menos que isso.
    O JSON traz o token: e lido em memoria e nunca impresso."""
    cmd = [_gcloud_exe(), "config", "config-helper", "--min-expiry=20m", "--format=json"]
    if GCLOUD_ACCOUNT:
        cmd.append(f"--account={GCLOUD_ACCOUNT}")
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    tok, exp = "", None
    try:
        cred = json.loads(out.stdout or "{}").get("credential") or {}
        tok = (cred.get("access_token") or "").strip()
        exp = dt.datetime.strptime(cred["token_expiry"], "%Y-%m-%dT%H:%M:%SZ")
    except Exception:  # noqa: BLE001
        pass
    if out.returncode != 0 or not tok or exp is None:
        raise RuntimeError(
            "sessao do gcloud invalida ou expirada — o Alexandre precisa rodar "
            "`gcloud auth login contato@manaca.tech` (aprovacao no navegador). "
            f"stderr: {(out.stderr or '')[:200]}")
    # google-auth considera expirado ~3 min 45 s antes de `expiry`; tiramos mais 2 min.
    return tok, exp - dt.timedelta(minutes=2)


_creds = None
_flex_client = None
# Flex PayGo (Vertex, endpoint global, pre-GA): 50% de desconto, latencia maior. So Gemini 3.x.
# https://docs.cloud.google.com/vertex-ai/generative-ai/docs/flex-paygo (lido em 2026-11-16)
FLEX_HEADERS = {"X-Vertex-AI-LLM-Request-Type": "shared",
                "X-Vertex-AI-LLM-Shared-Request-Type": "flex"}
FLEX_TIMEOUT_S = 300


def _credentials():
    global _creds
    if _creds is None:
        import google.oauth2.credentials as oc
        tok, exp = _mint_token()
        _creds = oc.Credentials(token=tok, expiry=exp,
                                refresh_handler=lambda request, scopes: _mint_token())
    return _creds


def get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION,
                               credentials=_credentials())
        dg._client = _client          # o worker passa a usar este cliente
    return _client


def get_flex_client():
    global _flex_client
    if _flex_client is None:
        from google import genai
        from google.genai import types as gt
        _flex_client = genai.Client(
            vertexai=True, project=GCP_PROJECT, location="global", credentials=_credentials(),
            http_options=gt.HttpOptions(api_version="v1", headers=FLEX_HEADERS,
                                        timeout=FLEX_TIMEOUT_S * 1000))
    return _flex_client


def flex_ok(model: str) -> bool:
    return model.startswith("gemini-3")


# ── Medicao: toda resposta do modelo e cobrada no ledger (inclui retries) ────
_BUDGET: Budget | None = None
_RUN_CTX = {"campaign": CAMPAIGN, "stage": "", "arm": "", "rep": 0}
_CALLS = {"n": 0, "flex": 0, "standard": 0}
_orig_call_model = dg._call_model


def _metered_call_model(image_paths, system_prompt, user_prompt, model_name, response_schema,
                        *args, **kwargs):
    resp = _orig_call_model(image_paths, system_prompt, user_prompt, model_name,
                            response_schema, *args, **kwargs)
    try:
        md = getattr(resp, "usage_metadata", None)
        if md is not None and _BUDGET is not None:
            traffic = str(getattr(md, "traffic_type", "") or "")
            is_flex = "FLEX" in traffic.upper()
            _BUDGET.charge(
                model=model_name,
                tok_in=int(getattr(md, "prompt_token_count", 0) or 0),
                tok_out=int(getattr(md, "candidates_token_count", 0) or 0),
                tok_think=int(getattr(md, "thoughts_token_count", 0) or 0),
                ctx=dict(_RUN_CTX, n_images=len(image_paths), traffic=traffic),
                discount=0.5 if is_flex else 1.0)
            _CALLS["n"] += 1
            _CALLS["flex" if is_flex else "standard"] += 1
    except Exception:  # noqa: BLE001 — medir nunca pode derrubar a chamada
        pass
    return resp


dg._call_model = _metered_call_model


# ── Dataset / janela ─────────────────────────────────────────────────────────
DS = {"name": "official"}
TESTSPACE = Path(os.environ.get("SAIRA_TESTSPACE_DATASETS", r"C:\Saira-testspace\datasets"))


def _load_testspace(name, cats, only):
    """Datasets do testspace do Gabriel (ex.: pi-inicial-v1). Gabarito = status do operador
    (CONFIRMADO -> tp, REJEITADO -> fp). So tem eventos em que a PRODUCAO criou deteccao,
    entao mede retencao do que o pipeline atual pega, nao o que ele deixa passar. Eventos que
    tambem estao no dataset oficial ficam de fora, para o conjunto servir de holdout temporal.
    Sem informacao de coalescencia: cada evento conta como uma deteccao."""
    root = TESTSPACE / name
    cat = json.loads((root / "catalogo.json").read_text(encoding="utf-8"))
    official = {p.name for c in ("tp", "fp", "indefinido", "baseline")
                for p in (CAM / c).iterdir() if p.is_dir()}
    rows = []
    for e in cat["eventos"]:
        eid = e["event_id"]
        if eid in official:
            continue
        c = {"CONFIRMADO": "tp", "REJEITADO": "fp"}.get(e.get("estado_plataforma"), "indefinido")
        if (cats and c not in cats) or (only and eid not in only):
            continue
        frames = sorted((root / e.get("origem_dispositivo", "pi-cam-001") / "frames" / eid).glob("*.jpg"))
        if len(frames) < 2:
            continue
        rows.append({"event_id": eid, "category": c, "frames": frames, "det_id": eid})
    rows.sort(key=lambda r: r["event_id"])
    return rows


def load_events(cats=None, limit=None, only=None):
    if DS["name"] != "official":
        return _load_testspace(DS["name"], cats, only)
    rows = []
    for cat in ("tp", "fp", "indefinido", "baseline"):
        if cats and cat not in cats:
            continue
        for lab in sorted((CAM / cat).glob("*/label.json")):
            L = json.loads(lab.read_text(encoding="utf-8"))
            if only and L["event_id"] not in only:
                continue
            frames = sorted((lab.parent / "frames").glob("*.jpg"))
            if len(frames) < 2:
                continue
            rows.append({"event_id": L["event_id"], "category": cat, "frames": frames,
                         "det_id": L.get("source_detection_id", L["event_id"])})
    rows.sort(key=lambda r: r["event_id"])
    if limit:
        out, seen = [], {}
        for r in rows:
            seen.setdefault(r["category"], 0)
            if seen[r["category"]] < limit:
                out.append(r)
                seen[r["category"]] += 1
        return out
    return rows


def build_window(frames):
    win = event_windows.subsample_frames(frames, cfg.GEMINI_CASCADE_MAX_FRAMES)
    return event_windows.fit_frames_to_payload(win, cfg.GEMINI_MAX_PAYLOAD_BYTES)


def camera_context(win):
    hh = ""
    try:
        parts = win[-1].name.split("_")[1].split("-")
        hh = f"{parts[0]}:{parts[1]}"
    except Exception:  # noqa: BLE001
        pass
    return {"camera_name": CAMERA_ROW["name"], "device_id": CAMERA_ROW["device_id"],
            "logradouro": CAMERA_ROW["logradouro"], "bairro": CAMERA_ROW["bairro"],
            "rpa": CAMERA_ROW["rpa"], "horario_local": hh}


def gate_mids(win):
    """Identico a main.py:1461-1470 (mids uniformes, sem as pontas)."""
    n = len(win)
    mid_count = max(0, cfg.GEMINI_GATE_MID_FRAMES)
    if n < 3 or mid_count == 0:
        return None
    step = (n - 1) / (mid_count + 1)
    ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
    ks = [k for k in ks if 0 < k < n - 1]
    return [win[k] for k in ks] or None


def even_subsample(frames, k):
    n = len(frames)
    if not k or n <= k:
        return frames
    idxs = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
    return [frames[i] for i in idxs]


def apply_prompt(variant: str) -> str:
    """Devolve o prompt_version a passar ao worker; v4 entra por rebind (como na camp 49)."""
    if variant == "v4":
        dg.NEW_LITTER_SYSTEM_PROMPT = p_v4.V4_GATE_PROMPT
        dg.SYSTEM_PROMPT = p_v4.V4_DETAIL_PROMPT
        return "current"
    dg.NEW_LITTER_SYSTEM_PROMPT = _V1_GATE
    dg.SYSTEM_PROMPT = _V1_DETAIL
    return "g3" if variant == "g3" else "current"


_FLEX = {"on": False}


def make_override(spec, default_model: str):
    """None quando a chamada e identica a de producao (mesmo modelo, sem ajustes)."""
    use_flex = _FLEX["on"] and flex_ok(spec["model"])
    if (spec["model"] == default_model and not spec.get("think") and not spec.get("media")
            and not use_flex):
        return None
    return dg.ModelOverride(model=spec["model"], thinking_level=spec.get("think"),
                            media_resolution=spec.get("media"),
                            client=get_flex_client() if use_flex else None)


def call_backoff(fn, tries=4):
    for att in range(1, tries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            transient = any(t in msg for t in ("429", "RESOURCE_EXHAUSTED", "503",
                                               "UNAVAILABLE", "500", "timeout", "Timeout"))
            if not transient or att == tries:
                raise
            time.sleep(min(60, 6 * 2 ** (att - 1)) * (0.7 + 0.6 * random.random()))


def usage_tuple(usage):
    return (int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
            int(getattr(usage, "thinking_tokens", 0) or 0))


# ── Estagios ─────────────────────────────────────────────────────────────────
def out_dir() -> Path:
    d = RESULTS if DS["name"] == "official" else RESULTS / DS["name"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_path(stage: str, arm: str, rep: int) -> Path:
    return out_dir() / f"{stage}__{arm}__r{rep}.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def latest_ok(path: Path) -> dict[str, dict]:
    """Ultimo registro SEM erro por evento."""
    ok = {}
    for r in read_jsonl(path):
        if not r.get("error"):
            ok[r["event_id"]] = r
    return ok


_write_lock = threading.Lock()


def append_jsonl(path: Path, rec: dict) -> None:
    with _write_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_gate_one(ev, arm, spec, rep, pv):
    win = build_window(ev["frames"])
    mids = gate_mids(win)
    rec = {"stage": "gate", "arm": arm, "rep": rep, "event_id": ev["event_id"],
           "det_id": ev["det_id"], "category": ev["category"], "model": spec["model"],
           "n_raw": len(ev["frames"]), "n_window": len(win), "n_sent": 2 + len(mids or []),
           "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
    if _BUDGET.stop:
        rec["error"] = "budget_stop"
        return rec
    try:
        t0 = time.time()
        g = call_backoff(lambda: dg.analyze_new_litter_with_gemini(
            first_frame=win[0], last_frame=win[-1], camera_context=camera_context(win),
            request_id=str(uuid4()), prior_window_context=None,
            use_mosaic=cfg.GEMINI_MOSAIC_AGENT1, mid_frames=mids, prompt_version=pv,
            override=make_override(spec, "gemini-2.5-flash-lite")))
        gr = g.report
        ti, to, tt = usage_tuple(g.usage)
        conf = int(gr.confidence_0_100)
        rec.update({
            "new_litter": bool(gr.new_litter_detected), "conf": conf,
            "fire": int(bool(gr.new_litter_detected) and conf >= TRIGGER_THR),
            "scene_type": getattr(gr, "scene_type", ""),
            "vehicle_stopped": bool(getattr(gr, "vehicle_stopped", False)),
            "person_handling": bool(getattr(gr, "person_handling_material", False)),
            "new_ground": bool(getattr(gr, "new_ground_material", False)),
            "evidence": (getattr(gr, "evidence_summary", "") or "")[:500],
            "tok_in": ti, "tok_out": to, "tok_think": tt,
            "cost_usd": round(cost_usd(spec["model"], ti, to, tt), 8),
            "latency_ms": int((time.time() - t0) * 1000)})
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return rec


def run_detail_one(ev, arm, spec, rep, pv):
    win = even_subsample(build_window(ev["frames"]), spec.get("frames"))
    rec = {"stage": "detail", "arm": arm, "rep": rep, "event_id": ev["event_id"],
           "det_id": ev["det_id"], "category": ev["category"], "model": spec["model"],
           "n_raw": len(ev["frames"]), "n_sent": len(win),
           "ts": dt.datetime.now().isoformat(timespec="seconds"), "error": ""}
    if _BUDGET.stop:
        rec["error"] = "budget_stop"
        return rec
    try:
        t0 = time.time()
        d = call_backoff(lambda: dg.analyze_with_gemini(
            image_paths=win, camera_context=camera_context(win), request_id=str(uuid4()),
            mosaic_mode=cfg.GEMINI_MOSAIC_AGENT2, prior_window_context=None,
            prompt_version=pv, override=make_override(spec, "gemini-2.5-flash")))
        dr = d.report
        ti, to, tt = usage_tuple(d.usage)
        rec.update({
            "disposal": int(bool(dr.infraction_confirmed)),
            "conf": int(getattr(dr, "confidence_0_100", 0) or 0),
            "waste_type": getattr(dr, "waste_type", "") or "",
            "offender_detected": bool(getattr(dr, "offender_detected", False)),
            "evidence": (getattr(dr, "evidence_summary", "") or "")[:700],
            "tok_in": ti, "tok_out": to, "tok_think": tt,
            "cost_usd": round(cost_usd(spec["model"], ti, to, tt), 8),
            "latency_ms": int((time.time() - t0) * 1000)})
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return rec


def pid_alive(pid: int) -> bool:
    """No Windows, os.kill(pid, 0) pode ENCERRAR o processo; consulta o tasklist."""
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def parse_ref(ref: str) -> tuple[str, int]:
    arm, _, rep = ref.partition(":")
    return arm, int(rep or 1)


def events_from(refs: str) -> set[str]:
    """Uniao dos eventos que DISPARARAM em algum dos gates citados (braco:rep,...)."""
    ids: set[str] = set()
    for ref in refs.split(","):
        arm, rep = parse_ref(ref.strip())
        path = out_path("gate", arm, rep)
        if not path.exists():
            raise SystemExit(f"gate {arm}:{rep} ainda nao rodou ({path.name})")
        ids |= {e for e, r in latest_ok(path).items() if r.get("fire") == 1}
    return ids


def run_stage(stage: str, a) -> None:
    global _BUDGET
    arms = GATE_ARMS if stage == "gate" else DETAIL_ARMS
    if a.arm not in arms:
        raise SystemExit(f"braco '{a.arm}' desconhecido para {stage}: {sorted(arms)}")
    spec = arms[a.arm]
    cats = a.cats.split(",") if a.cats else None
    only = None
    if stage == "detail":
        if a.events_from:
            only = events_from(a.events_from)
        elif not cats:
            raise SystemExit("detail exige --events-from <gate:rep,...> ou --cats")
    events = load_events(cats, a.limit, only)
    path = out_path(stage, a.arm, a.rep)
    done = latest_ok(path)
    todo = [e for e in events if e["event_id"] not in done]
    _FLEX["on"] = bool(getattr(a, "flex", False)) and flex_ok(spec["model"])
    if getattr(a, "flex", False) and not _FLEX["on"]:
        print(f"  aviso: --flex ignorado, {spec['model']} nao tem Flex PayGo")
    est = len(todo) * spec["est"] * (0.5 if _FLEX["on"] else 1.0)
    if _FLEX["on"]:
        # Flex tem latencia maior; timeout curto do cliente = chamada paga e perdida.
        cfg.GEMINI_TIMEOUT_SECONDS = FLEX_TIMEOUT_S
        cfg.GEMINI_AGENT1_TIMEOUT_SECONDS = FLEX_TIMEOUT_S
    print(f"[{stage}] braco={a.arm} rep={a.rep} modelo={spec['model']} prompt={spec['prompt']} "
          f"think={spec.get('think')} media={spec.get('media')} frames={spec.get('frames')} "
          f"flex={_FLEX['on']}")
    print(f"  eventos={len(events)} ja_feitos={len(events) - len(todo)} a_rodar={len(todo)} "
          f"estimativa=US$ {est:.3f}")
    if a.dry_run:
        wins = [len(build_window(e["frames"])) for e in todo]
        if wins:
            print(f"  janela: mediana={sorted(wins)[len(wins) // 2]} min={min(wins)} max={max(wins)}")
        return
    if not todo:
        print("  nada a rodar")
        return
    _BUDGET = Budget()
    _BUDGET.run_cap = a.max_usd
    print(f"  orcamento: teto US$ {_BUDGET.cap:.2f} gasto US$ {_BUDGET.spent:.4f} "
          f"teto desta execucao US$ {a.max_usd:.2f}")
    _BUDGET.require(est, f"{stage}/{a.arm}")
    _RUN_CTX.update({"stage": stage, "arm": a.arm, "rep": a.rep})
    # trava por (estagio, braco, rep): duas execucoes iguais ao mesmo tempo pagariam em dobro
    lock = out_dir() / f".lock__{stage}__{a.arm}__r{a.rep}"
    if lock.exists():
        try:
            other = int(lock.read_text(encoding="utf-8").split()[0])
        except Exception:  # noqa: BLE001
            other = 0
        if other and pid_alive(other):
            raise SystemExit(f"ja existe uma execucao de {stage}/{a.arm}/r{a.rep} em andamento "
                             f"(pid {other}); nao relance — espere ou confira o log.")
    lock.write_text(f"{os.getpid()} {dt.datetime.now().isoformat(timespec='seconds')}",
                    encoding="utf-8")
    get_client()
    pv = apply_prompt(spec["prompt"])
    fn = run_gate_one if stage == "gate" else run_detail_one
    n_ok = n_err = 0
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futs = [pool.submit(fn, ev, a.arm, spec, a.rep, pv) for ev in todo]
            for i, fut in enumerate(as_completed(futs), 1):
                r = fut.result()
                r["flex"] = _FLEX["on"]      # cost_usd do registro e sempre PRECO DE LISTA
                append_jsonl(path, r)
                if r["error"]:
                    n_err += 1
                    tag = "ERR " + r["error"][:70]
                else:
                    n_ok += 1
                    tag = (f"fire={r['fire']} conf={r['conf']} {r['scene_type']}" if stage == "gate"
                           else f"disposal={r['disposal']} conf={r['conf']}")
                print(f"  [{i}/{len(todo)}] {r['category']:10s} {r['event_id']} {tag}", flush=True)
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    print(f"  fim: ok={n_ok} erros={n_err} chamadas_cobradas={_CALLS['n']} "
          f"(flex={_CALLS['flex']} standard={_CALLS['standard']}) "
          f"gasto_desta_execucao=US$ {_BUDGET.run_spent:.4f} total_semana=US$ {_BUDGET.spent:.4f} "
          f"({int(time.time() - t0)} s)")


# ── Score (offline) ──────────────────────────────────────────────────────────
def _rate(hit, n):
    return round(100 * hit / n, 1) if n else None


def _wilson(hit, n, z=1.96):
    """Intervalo de Wilson de 95% em pontos percentuais, como 'lo-hi'. Com n pequeno
    (19 deteccoes reais) o intervalo e largo: e isso que impede declarar vencedor cedo."""
    if not n:
        return None
    p = hit / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return f"{max(0.0, 100 * (mid - half)):.0f}-{min(100.0, 100 * (mid + half)):.0f}"


def score_pair(gate_ref: str, detail_ref: str, quiet=False) -> dict:
    garm, grep_ = parse_ref(gate_ref)
    darm, drep = parse_ref(detail_ref)
    gate = latest_ok(out_path("gate", garm, grep_))
    detail = latest_ok(out_path("detail", darm, drep))
    events = load_events()
    rows, missing_gate, missing_detail = [], [], []
    for ev in events:
        g = gate.get(ev["event_id"])
        if g is None:
            missing_gate.append(ev["event_id"])
            continue
        fired = g.get("fire") == 1
        d = detail.get(ev["event_id"]) if fired else None
        if fired and d is None:
            missing_detail.append(ev["event_id"])
            continue
        rows.append({"event_id": ev["event_id"], "det_id": ev["det_id"],
                     "category": ev["category"], "gate_fire": int(fired),
                     "disposal": int(bool(fired and d and d.get("disposal") == 1)),
                     "gate_cost": float(g.get("cost_usd") or 0.0),
                     "detail_cost": float(d.get("cost_usd") or 0.0) if d else 0.0})

    def evt(cat, field):
        sub = [r for r in rows if r["category"] == cat]
        return sum(r[field] for r in sub), len(sub)

    def det(cat, field):
        byd: dict[str, list[int]] = {}
        for r in rows:
            if r["category"] == cat:
                byd.setdefault(r["det_id"], []).append(r[field])
        return sum(1 for v in byd.values() if any(v)), len(byd)

    tp_d, tp_dn = det("tp", "disposal")
    fp_d, fp_dn = det("fp", "disposal")
    tp_e, tp_en = evt("tp", "disposal")
    fp_e, fp_en = evt("fp", "disposal")
    bl_e, bl_en = evt("baseline", "disposal")
    gtp_d, _ = det("tp", "gate_fire")
    gfp_d, _ = det("fp", "gate_fire")
    gbl_e, _ = evt("baseline", "gate_fire")
    n = len(rows)
    n_fire = sum(r["gate_fire"] for r in rows)
    gate_cost = sum(r["gate_cost"] for r in rows)
    detail_cost = sum(r["detail_cost"] for r in rows)
    c_gate = gate_cost / n if n else 0.0
    c_detail = detail_cost / n_fire if n_fire else 0.0
    out = {
        "gate": gate_ref, "detail": detail_ref, "n_events": n,
        "missing_gate": len(missing_gate), "missing_detail": len(missing_detail),
        "recall_det": _rate(tp_d, tp_dn), "tp_det": f"{tp_d}/{tp_dn}",
        "recall_det_ci95": _wilson(tp_d, tp_dn),
        "fp_rate_det": _rate(fp_d, fp_dn), "fp_det": f"{fp_d}/{fp_dn}",
        "fp_rate_det_ci95": _wilson(fp_d, fp_dn),
        "precision_det": _rate(tp_d, tp_d + fp_d),
        "recall_evt": _rate(tp_e, tp_en), "tp_evt": f"{tp_e}/{tp_en}",
        "fp_rate_evt": _rate(fp_e, fp_en), "fp_evt": f"{fp_e}/{fp_en}",
        "baseline_fire": _rate(bl_e, bl_en), "baseline": f"{bl_e}/{bl_en}",
        "gate_pass_tp_det": f"{gtp_d}/{tp_dn}", "gate_pass_fp_det": f"{gfp_d}/{fp_dn}",
        "gate_pass_baseline": f"{gbl_e}/{bl_en}",
        "gate_pass_rate": _rate(n_fire, n),
        "cost_gate_per_call": round(c_gate, 6), "cost_detail_per_call": round(c_detail, 6),
        "cost_per_event_dataset": round((gate_cost + detail_cost) / n, 6) if n else None,
        # projecao para o mix de producao: custo = gate + p_passa * detail
        "p_pass_prod": P_PASS_PROD,
        "cost_per_event_prod": round(c_gate + P_PASS_PROD * c_detail, 6),
        "cost_per_event_prod_p05": round(c_gate + 0.05 * c_detail, 6),
    }
    if not quiet:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def run_matrix(a) -> None:
    """Tabela de todos os pares (gate, detail) que ja tem resultado em disco."""
    gates = sorted(p.name[len("gate__"):-len(".jsonl")].replace("__r", ":")
                   for p in out_dir().glob("gate__*__r*.jsonl") if not p.name.endswith("__r0.jsonl"))
    details = sorted(p.name[len("detail__"):-len(".jsonl")].replace("__r", ":")
                     for p in out_dir().glob("detail__*__r*.jsonl") if not p.name.endswith("__r0.jsonl"))
    if a.gate:
        gates = [g for g in gates if g in a.gate.split(",")]
    rows = []
    for g in gates:
        for d in details:
            s = score_pair(g, d, quiet=True)
            if s["n_events"] and s["missing_detail"] <= a.max_missing:
                rows.append(s)
    cols = ["gate", "detail", "tp_det", "recall_det", "recall_det_ci95", "fp_det", "fp_rate_det",
            "precision_det",
            "baseline", "tp_evt", "fp_evt", "cost_detail_per_call", "cost_per_event_dataset",
            "cost_per_event_prod", "missing_detail"]
    print(" | ".join(cols))
    for s in rows:
        print(" | ".join(str(s[c]) for c in cols))
    (out_dir() / "matrix.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                           encoding="utf-8")


def run_probe(a) -> None:
    """Mede tokens e custo reais do detail em poucos eventos (paga essas chamadas)."""
    global _BUDGET
    spec = DETAIL_ARMS[a.arm]
    events = [e for e in load_events(["tp", "fp"]) if len(e["frames"]) >= 30][: a.n]
    _BUDGET = Budget()
    _BUDGET.run_cap = a.max_usd
    _BUDGET.require(len(events) * spec["est"], f"probe/{a.arm}")
    _RUN_CTX.update({"stage": "probe", "arm": a.arm, "rep": 0})
    _FLEX["on"] = bool(a.flex) and flex_ok(spec["model"])
    if _FLEX["on"]:
        cfg.GEMINI_TIMEOUT_SECONDS = FLEX_TIMEOUT_S
    get_client()
    pv = apply_prompt(spec["prompt"])
    for ev in events:
        r = run_detail_one(ev, a.arm, spec, 0, pv)
        keep = {k: r.get(k) for k in ("event_id", "category", "n_sent", "disposal", "conf",
                                      "tok_in", "tok_out", "tok_think", "cost_usd",
                                      "latency_ms", "error")}
        print(json.dumps(keep, ensure_ascii=False))
    print(f"gasto do probe: US$ {_BUDGET.run_spent:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="official",
                    help="official (cam_picam001) ou um dataset do testspace, ex.: pi-inicial-v1; "
                         "vem ANTES do subcomando")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for stage in ("gate", "detail"):
        p = sub.add_parser(stage)
        p.add_argument("--arm", required=True)
        p.add_argument("--rep", type=int, default=1)
        p.add_argument("--cats", default=None)
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--max-usd", type=float, default=0.50,
                       help="teto de gasto desta execucao")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--flex", action="store_true",
                       help="Flex PayGo (50%% de desconto; so Gemini 3.x; latencia maior)")
        if stage == "detail":
            p.add_argument("--events-from", default=None,
                           help="gate(s) cujos disparos definem os eventos: braco:rep[,braco:rep]")
    p = sub.add_parser("score")
    p.add_argument("--gate", required=True)
    p.add_argument("--detail", required=True)
    p = sub.add_parser("matrix")
    p.add_argument("--gate", default=None, help="restringe a estes gates (braco:rep,...)")
    p.add_argument("--max-missing", type=int, default=0,
                   help="aceita pares com ate N eventos disparados sem detail")
    p = sub.add_parser("probe")
    p.add_argument("--arm", required=True)
    p.add_argument("--n", type=int, default=2)
    p.add_argument("--max-usd", type=float, default=0.15)
    p.add_argument("--flex", action="store_true")
    a = ap.parse_args()
    DS["name"] = a.dataset
    _RUN_CTX["dataset"] = a.dataset
    try:
        if a.cmd == "list":
            print("GATE:", json.dumps(GATE_ARMS, indent=1))
            print("DETAIL:", json.dumps(DETAIL_ARMS, indent=1))
        elif a.cmd in ("gate", "detail"):
            run_stage(a.cmd, a)
        elif a.cmd == "score":
            score_pair(a.gate, a.detail)
        elif a.cmd == "matrix":
            run_matrix(a)
        elif a.cmd == "probe":
            run_probe(a)
    except BudgetExceeded as exc:
        print(f"ORCAMENTO: {exc}")
        sys.exit(3)


if __name__ == "__main__":
    main()
