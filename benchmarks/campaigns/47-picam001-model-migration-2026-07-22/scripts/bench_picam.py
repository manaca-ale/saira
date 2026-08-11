#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camp 47 — pi-cam-001 model-migration A/B (current vs Gemini-3 replacements).

Replays the REAL production cascade (gate Agent-1 -> detail Agent-2) over the
cam_picam001 dataset, per EVENT (event-driven window), for several model pairs.

FIDELITY (event-driven path, matches worker.main._process_event_device exactly):
  window = sorted(event/frames/*.jpg)
         -> event_windows.subsample_frames(., GEMINI_CASCADE_MAX_FRAMES=48)
         -> event_windows.fit_frames_to_payload(., GEMINI_MAX_PAYLOAD_BYTES=8_000_000)
  gate   = analyze_new_litter_with_gemini(first=win[0], last=win[-1], mid_frames=3 mids)
  trigger= new_litter_detected and confidence_0_100 >= 85   (main.py:1674)
  detail = analyze_with_gemini(image_paths=win)   only when the gate triggers
  prompt = config.GEMINI_PROMPT_VERSION (V1); NO crops / DINOv2 / structural (esp32-only).

CAVEAT (documented): the gate first_frame in prod may be the previous window's last
frame (mutable STATE_DIR state, not reproducible from DB). We use first=win[0].
prior_window_context is not reconstructed (=None) -> effective_threshold = 85.

Arms (gate | detail):
  current  gemini-2.5-flash-lite | gemini-2.5-flash        (prod today)
  repl     gemini-3.1-flash-lite | gemini-3.6-flash        (Google-recommended replacements)
  cheap    gemini-3.1-flash-lite | gemini-3.5-flash-lite   (cheaper detail candidate)

Ground truth (label.json category): tp=should fire, fp/baseline=should NOT fire,
indefinido=excluded from recall/FP. Billing = Vertex saira-tests-260520 (ADC).

Usage:
  python scripts/bench_picam.py --arms current --limit 3 --dry-run   # validate input
  python scripts/bench_picam.py --arms current --limit 3             # fidelity check
  python scripts/bench_picam.py --arms current,repl,cheap --workers 4
  python scripts/bench_picam.py --aggregate-only
"""
from __future__ import annotations
import argparse, csv, json, os, random, sys, time, warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

warnings.filterwarnings("ignore")
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"c:\saira")
HERE = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "data" / "datasets" / "official"
CAM = OFFICIAL / "cam_picam001"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
CSV_PATH = RESULTS / "bench_picam.csv"
SUMMARY_PATH = RESULTS / "bench_picam_summary.json"

# ── Auth de TESTE: AI Studio API key (conta Saira - Testes) ──────────────────
# Caminho API-key (GEMINI_USE_VERTEX=false) — o ADC Vertex expirou e a key
# registrada no .env.benchmark está 429. A key de teste ativa é passada por env
# GEMINI_TEST_API_KEY (NUNCA hardcoded aqui, NUNCA a key de produção).
_TEST_KEY = os.environ.get("GEMINI_TEST_API_KEY", "").strip()
if not _TEST_KEY:
    sys.exit("defina GEMINI_TEST_API_KEY no ambiente (chave AI Studio da conta Saira - Testes)")
os.environ["GEMINI_USE_VERTEX"] = "false"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "false"
os.environ["GEMINI_API_KEY"] = _TEST_KEY

# ── PROD-exact window/model env (event-driven pi-cam-001) BEFORE worker.config ──
# window caps = prod (docker inspect saira-yolo-worker-prod, 22/07)
os.environ["GEMINI_CASCADE_MAX_FRAMES"] = "48"
os.environ["GEMINI_MAX_PAYLOAD_BYTES"] = "8000000"
os.environ["GEMINI_GATE_MID_FRAMES"] = "3"
os.environ["GEMINI_AGENT1_TRIGGER_MIN_CONFIDENCE"] = "85"
os.environ["GEMINI_AGENT1_THINKING_BUDGET"] = "1024"
# 8192 p/ absorver JSON verboso + raciocínio (evita truncamento sob thinking=high)
os.environ["GEMINI_MAX_OUTPUT_TOKENS"] = "8192"
os.environ["GEMINI_AGENT1_MAX_OUTPUT_TOKENS"] = "8192"
os.environ["GEMINI_TIMEOUT_SECONDS"] = "45"
# default models (arms override at call time via env)
os.environ.setdefault("GEMINI_MODEL", "gemini-2.5-flash")
os.environ.setdefault("GEMINI_AGENT1_MODEL", "gemini-2.5-flash-lite")
os.environ.setdefault("DATABASE_URL", "postgresql://bench:bench@localhost/bench")

sys.path.insert(0, str(ROOT / "services" / "yolo-worker-vm" / "src"))
import worker.config as cfg                     # noqa: E402
import worker.event_windows as event_windows    # noqa: E402
import worker.detector_gemini as dg             # noqa: E402
from worker.detector_gemini import (            # noqa: E402
    analyze_new_litter_with_gemini, analyze_with_gemini,
)
try:
    from google.genai import types as genai_types  # noqa: E402
except Exception:
    genai_types = None

# ── Prompts otimizados para Gemini-3 (pesquisa saira_vlm_vision_performance.md) ──
# Princípios: (1) RACIOCÍNIO-PRIMEIRO antes do JSON — evita a "Anomalia C3" (sob
# schema estrito sem CoT, o modelo preenche slots por prior e sub-dispara);
# (2) inclui descarte A PÉ (não exige veículo) — recall na pi-cam-001 residencial;
# (3) sinal de PERMANÊNCIA (depositar-e-deixar) p/ especificidade; (4) coleta ≠ descarte.
# Emparelhado com thinking_level=high nos modelos Gemini-3.
G3_GATE_PROMPT = """
You are a spatio-temporal analyst for a FIXED CCTV camera at a KNOWN illegal-dumping
HOTSPOT on a Brazilian residential street. There is usually a pre-existing waste PILE
at the curb. You receive 2-5 chronological frames from the SAME camera. Decide whether
an illegal WASTE-DUMPING act occurs within this sequence. The mission prioritizes
RECALL: do not miss real deposits.

REASON STEP BY STEP BEFORE ANSWERING (put the reasoning in scene_delta_analysis and
evidence_summary, THEN set the booleans):
1) BASELINE: describe the first frame — fixed infrastructure and the existing waste pile.
2) ACTORS & TRAJECTORY: track each person/vehicle. Do they merely MOVE THROUGH (different
   position each frame, never interacting with the pile/ground), or do they STOP and
   INTERACT with the pile/ground area?
3) DELTA: compare first vs last frame at the pile/deposit area. Did the pile GROW, did a
   new object appear, or did an actor bring material to the pile?

new_litter_detected=true when an actor STOPS and adds material at the pile/ground, in
EITHER form:
- ON FOOT: a person carries an object/bag and places/drops it at the pile or on the
  ground. NO vehicle is required.
- WITH VEHICLE: a vehicle stops and a person handles/unloads material, or an
  open-bed/tipper discharges near the pile.
Positive signals (ANY is enough): the pile is visibly LARGER or has NEW items in the
last frame; a person crouches/bends at the pile; a new object rests on the ground that
was absent before; a stopped vehicle with a person moving material toward the pile.
The deposited material does NOT need to stay isolated — merging into the existing pile
(pile grows) still counts. You do NOT need to witness the actor leave.

AMBIGUITY RULE (recall-first): if a person or vehicle STOPS and handles material right
at this dumping pile and you cannot tell loading from unloading, DEFAULT to DUMPING —
residents removing waste from this monitored hotspot is rare; adding to it is the norm.

new_litter_detected=false ONLY when:
- Pure pass-through: an actor crosses WITHOUT stopping or interacting with the pile
  (carries a bag straight out of frame; nothing added at the pile).
- Passenger pickup/dropoff with no material handled at the pile; moving traffic;
  pedestrians merely walking or standing away from the pile.
- The pile is clearly UNCHANGED between first and last frame and nobody interacted.
- Shadow/lighting changes only.
- An obvious MARKED municipal collection truck / uniformed crew REMOVING the pile
  (pile clearly SHRINKS).

scene_type: EMPTY (no actors), TRAFFIC (actors moving through, no pile interaction),
PARKED (vehicle stationary, nobody handling material), DUMPING (stop-and-add as above).

Do not fabricate a positive with no actor present; but when an actor interacts with the
pile, lean toward DUMPING. Set vehicle_stopped, person_handling_material and
new_ground_material from the evidence; report first_frame_has_litter /
last_frame_has_litter about the pile state. Respond with ONLY valid JSON.
""".strip()

G3_DETAIL_PROMPT = """
Você é um auditor visual de descarte irregular de resíduos em via pública no Brasil,
monitorando uma câmera fixa em um PONTO CRÔNICO de descarte residencial (normalmente há
uma PILHA de lixo pré-existente na guia). Recebe frames cronológicos da MESMA câmera.
Responda APENAS JSON válido. A missão prioriza RECALL: não perca depósitos reais.

RACIOCINE ANTES DE DECIDIR (produza o raciocínio em evidence_summary; só ENTÃO defina
infraction_confirmed):
1) BASELINE: descreva o primeiro frame — infraestrutura fixa e a pilha existente.
2) ATORES E TRAJETÓRIA: rastreie cada pessoa/veículo. Apenas PASSA (posições diferentes,
   sem interagir com a pilha) ou PARA e INTERAGE com a pilha/chão?
3) DELTA: compare o primeiro vs o último frame na área da pilha. A pilha CRESCEU, surgiu
   objeto novo, ou um ator levou material até a pilha?

infraction_confirmed=true quando um ator PARA e adiciona material à pilha/chão, em
QUALQUER forma:
A) A PÉ: uma pessoa carrega objeto/saco e o coloca/joga na pilha ou no chão. NÃO exige
   veículo.
B) COM VEÍCULO: veículo parado com pessoa manuseando/descarregando material; ou caçamba
   aberta/basculante descarregando junto à pilha.
Sinais positivos (QUALQUER um basta): a pilha está visivelmente MAIOR ou com itens NOVOS
no último frame; pessoa se agacha/curva junto à pilha; objeto novo no chão que não havia
antes; veículo parado com pessoa levando material à pilha. O material NÃO precisa ficar
isolado — fundir-se à pilha existente (pilha cresce) já conta. NÃO é preciso ver o ator
ir embora.

REGRA DE AMBIGUIDADE (recall-first): se uma pessoa ou veículo PARA e manuseia material
junto a esta pilha e você não consegue distinguir carregar de descarregar, ASSUMA
DESCARTE — neste ponto monitorado, morador remover lixo é raro; adicionar é a norma.

infraction_confirmed=false SOMENTE quando:
- Passagem pura: ator atravessa SEM parar/interagir com a pilha (leva o saco para fora do
  quadro; nada é adicionado).
- Embarque/desembarque de passageiros sem manuseio de material na pilha; trânsito normal;
  pedestre apenas andando/parado longe da pilha.
- Pilha claramente INALTERADA entre primeiro e último frame e ninguém interagiu.
- Mudança apenas de sombra/iluminação.
- Caminhão de COLETA municipal MARCADO / equipe uniformizada REMOVENDO a pilha (pilha
  claramente DIMINUI).

Não invente positivo sem ator presente; mas quando um ator interage com a pilha, PENDA
para descarte. Inclua bounding boxes normalizados 0-1000 [y_min, x_min, y_max, x_max]:
waste_bbox (resíduo, quando isolável) e offender_bbox (autor/veículo, quando visível).
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico. offender_detected descreve
apenas a capacidade de identificar o autor/veículo. Campo não inferível = null.
""".strip()

# Thinking override (por braço). Quando setado, TODA chamada Gemini do braço usa
# thinking_level em vez de thinking_budget. Arms rodam sequencialmente (sem corrida).
_G3_THINK = {"level": None}
_MEDIA_RES = {"res": None}   # None | "low" | "medium" | "high"  (por braço)
_orig_bgc = dg._build_generate_config
def _patched_bgc(schema, max_output_tokens=None, thinking_budget=None, seed=None):
    lvl = _G3_THINK["level"]; mres = _MEDIA_RES["res"]
    if (lvl or mres) and genai_types is not None:
        gc = genai_types.GenerateContentConfig(
            temperature=cfg.GEMINI_TEMPERATURE,
            max_output_tokens=max_output_tokens or cfg.GEMINI_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json", response_schema=schema,
            thinking_config=genai_types.ThinkingConfig(thinking_level=lvl) if lvl else None,
            seed=seed)
        if mres:
            gc.media_resolution = getattr(genai_types.MediaResolution,
                                          f"MEDIA_RESOLUTION_{mres.upper()}")
        return gc
    return _orig_bgc(schema, max_output_tokens, thinking_budget, seed)
dg._build_generate_config = _patched_bgc

# ── Variante ESPECIFICIDADE-FIRST (g3s): exige evidência de DEPÓSITO (delta),
# não mera presença. Remove o default "ambíguo→descarte". Mantém descarte a pé. ──
G3S_GATE_PROMPT = """
You are a spatio-temporal analyst for a FIXED CCTV camera at a KNOWN illegal-dumping
HOTSPOT on a Brazilian residential street. There is usually a pre-existing waste PILE at
the curb. You receive 2-5 chronological frames from the SAME camera. Decide whether an
illegal WASTE-DUMPING act OCCURS WITHIN THIS SEQUENCE. Precision matters: only confirm a
deposit you can actually SEE happen — a person merely being near the pile is NOT enough.

REASON STEP BY STEP BEFORE ANSWERING (fill scene_delta_analysis and evidence_summary,
THEN set the booleans):
1) BASELINE: describe the first frame — fixed infrastructure and the existing pile.
2) ACTORS & TRAJECTORY: track each person/vehicle across frames.
3) DEPOSIT DELTA: compare first vs last frame at the pile/ground. Is there CONCRETE
   evidence that material was ADDED during this sequence?

new_litter_detected=true ONLY when you see a DEPOSIT DELTA — at least one of:
- a NEW object/bag/material on the ground or pile in a later frame that was ABSENT
  earlier and REMAINS after the actor moves on;
- the pile visibly GREW / gained items between first and last frame;
- a person clearly carrying material and PLACING/DROPPING it at the pile (on foot — NO
  vehicle required), and the material stays;
- a stopped vehicle with a person actively UNLOADING material toward the pile, or an
  open-bed/tipper discharging.

new_litter_detected=false (this is the DEFAULT — most sequences) when:
- A person or vehicle is merely PRESENT, STOPPED, walking, or standing near the pile
  WITHOUT a visible add (presence/stopping alone is NOT a deposit).
- Carry-through: an actor passes carrying something but takes it away; nothing new remains.
- Passenger pickup/dropoff; moving traffic; pedestrians walking or standing.
- The pile looks the same at first and last frame.
- You are UNSURE whether material was added — if you cannot point to a specific new/added
  item that persists, answer false.
- Shadow/lighting changes; waste collection/removal (pile shrinks).

scene_type: EMPTY, TRAFFIC, PARKED, or DUMPING (only if a deposit delta is visible).
Anchor every positive to a concrete added item you can name in evidence_summary. If you
cannot, set new_litter_detected=false, confidence_0_100=0. Respond with ONLY valid JSON.
""".strip()

G3S_DETAIL_PROMPT = """
Você é um auditor visual de descarte irregular de resíduos em via pública no Brasil, numa
câmera fixa em PONTO CRÔNICO de descarte residencial (normalmente há uma PILHA pré-existente).
Recebe frames cronológicos da MESMA câmera. Responda APENAS JSON válido. Precisão importa:
só confirme um depósito que você REALMENTE veja acontecer — pessoa apenas PRESENTE perto da
pilha NÃO basta.

RACIOCINE ANTES DE DECIDIR (em evidence_summary; só ENTÃO defina infraction_confirmed):
1) BASELINE: primeiro frame — infraestrutura fixa e a pilha existente.
2) ATORES E TRAJETÓRIA: rastreie cada pessoa/veículo.
3) DELTA DE DEPÓSITO: compare primeiro vs último frame na pilha/chão. Há evidência
   CONCRETA de material ADICIONADO nesta sequência?

infraction_confirmed=true SOMENTE com um DELTA DE DEPÓSITO — ao menos um:
- objeto/saco/material NOVO no chão ou na pilha num frame posterior, AUSENTE antes, que
  PERMANECE após o ator seguir;
- a pilha visivelmente CRESCEU / ganhou itens entre o primeiro e o último frame;
- pessoa claramente carregando material e o COLOCANDO/JOGANDO na pilha (a pé — SEM exigir
  veículo), e o material fica;
- veículo parado com pessoa DESCARREGANDO material para a pilha, ou caçamba descarregando.

infraction_confirmed=false (é o PADRÃO — a maioria dos casos) quando:
- Pessoa/veículo apenas PRESENTE, PARADO, andando ou em pé perto da pilha SEM adição
  visível (presença/parada sozinha NÃO é depósito).
- Passagem: ator passa carregando algo mas leva embora; nada novo permanece.
- Embarque/desembarque; trânsito; pedestre andando/parado.
- A pilha parece igual no primeiro e no último frame.
- Você está EM DÚVIDA se houve adição — se não consegue apontar um item novo específico
  que permanece, responda false.
- Mudança de sombra/iluminação; coleta/remoção (pilha diminui).

Ancore todo positivo a um item adicionado concreto que você nomeie em evidence_summary. Se
não conseguir, infraction_confirmed=false. waste_bbox/offender_bbox 0-1000 quando visíveis.
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico. Campo não inferível = null.
""".strip()

_V1_GATE, _V1_DETAIL = dg.NEW_LITTER_SYSTEM_PROMPT, dg.SYSTEM_PROMPT

def apply_arm_prompts(prompt_variant):
    """Monkeypatch os prompts 'current' (gate+detail) por braço."""
    if prompt_variant == "g3":
        dg.NEW_LITTER_SYSTEM_PROMPT = G3_GATE_PROMPT
        dg.SYSTEM_PROMPT = G3_DETAIL_PROMPT
    elif prompt_variant == "g3s":
        dg.NEW_LITTER_SYSTEM_PROMPT = G3S_GATE_PROMPT
        dg.SYSTEM_PROMPT = G3S_DETAIL_PROMPT
    else:
        dg.NEW_LITTER_SYSTEM_PROMPT = _V1_GATE
        dg.SYSTEM_PROMPT = _V1_DETAIL

CAMERA_ROW = {"name": "Residencial Via Mangue III - 2", "device_id": "pi-cam-001",
              "logradouro": "Rua Professor Pedro Augusto Carneiro Leão",
              "bairro": "Imbiribeira", "rpa": "RPA-1"}
DEVICE_ID = "pi-cam-001"
TRIGGER_THR = 85

ARMS = {
    # baseline de prod
    "current":    {"gate": "gemini-2.5-flash-lite", "detail": "gemini-2.5-flash",     "prompt": "v1", "think": None},
    # substitutos Gemini-3 com prompt V1 antigo (camp anterior; 3.6-flash)
    "repl":       {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.6-flash",     "prompt": "v1", "think": None},
    "cheap":      {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.5-flash-lite", "prompt": "v1", "think": None},
    # ISOLAR thinking: substitutos + V1 + thinking=high (pesquisa: CoT é essencial p/ G3)
    "g3_v1":      {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.5-flash",     "prompt": "v1", "think": "high"},
    # PROMPT NOVO g3 + thinking=high (a correção)
    "g3_new":     {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.5-flash",     "prompt": "g3", "think": "high"},
    # UNIFICADO (2 estágios, mesmo modelo): 3.1-flash-lite p/ gate E detail
    "g3_unified": {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.1-flash-lite", "prompt": "g3", "think": "high"},
    # CHAMADA ÚNICA (recomendação primária da pesquisa): UMA chamada 3.1-flash-lite na
    # janela CHEIA, sem gate separado. Decisão direta = infraction_confirmed.
    "unified_single": {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.1-flash-lite", "prompt": "g3", "think": "high", "single": True},
    # media_resolution=low (input de imagem ~4× menor) — janela cheia
    "unified_low":    {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.1-flash-lite", "prompt": "g3", "think": "high", "single": True, "media": "low"},
    # lever nº de imagens: low-res + só 8 frames (even-spaced)
    "unified_low_8f": {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.1-flash-lite", "prompt": "g3", "think": "high", "single": True, "media": "low", "frames": 8},
    # low-res mantendo 2 estágios (gate 3.1 + detail 3.1) p/ comparar filtro vs chamada única
    "unified_low_2s": {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.1-flash-lite", "prompt": "g3", "think": "high", "media": "low"},
    # ESPECIFICIDADE-FIRST: 2-estágios low-res com prompt g3s (exige delta de depósito)
    "unified_low_2s_spec": {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.1-flash-lite", "prompt": "g3s", "think": "high", "media": "low"},
    # e a chamada única com o prompt especificidade-first, p/ comparar
    "unified_low_spec": {"gate": "gemini-3.1-flash-lite", "detail": "gemini-3.1-flash-lite", "prompt": "g3s", "think": "high", "media": "low", "single": True},
}


def even_subsample(frames, k):
    n = len(frames)
    if n <= k:
        return frames
    idxs = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
    return [frames[i] for i in idxs]
# USD per 1M tokens (in, out) — for cost recompute from real token counts.
# Nota: preço 3.5-flash é estimativa (pesquisa: camada "Médio"); custo é secundário aqui.
PRICE = {
    "gemini-2.5-flash-lite": (0.10, 0.40), "gemini-2.5-flash": (0.15, 0.60),
    "gemini-3.1-flash-lite": (0.125, 0.75), "gemini-3.6-flash": (1.50, 7.00),
    "gemini-3.5-flash-lite": (0.30, 2.50), "gemini-3.5-flash": (0.50, 4.00),
}


def load_events(limit=None, cats=None):
    rows = []
    for cat in ("tp", "fp", "indefinido", "baseline"):
        if cats and cat not in cats:
            continue
        for lab in sorted((CAM / cat).glob("*/label.json")):
            L = json.loads(lab.read_text(encoding="utf-8"))
            frames = sorted((lab.parent / "frames").glob("*.jpg"))
            if len(frames) < 2:
                continue
            rows.append({"event_id": L["event_id"], "category": cat,
                         "frames": frames, "datetime": L.get("datetime", ""),
                         "det_id": L.get("source_detection_id", L["event_id"])})
    rows.sort(key=lambda r: r["event_id"])
    if limit:
        # spread across categories: take first `limit` of each present cat
        out, seen = [], {}
        for r in rows:
            seen.setdefault(r["category"], 0)
            if seen[r["category"]] < limit:
                out.append(r); seen[r["category"]] += 1
        return out
    return rows


def camera_context(win):
    hh = ""
    try:
        # horario_local = HH:MM of last frame (main.py:1388) — name = YYYY-MM-DD_HH-MM-SS-...
        parts = win[-1].name.split("_")[1].split("-")
        hh = f"{parts[0]}:{parts[1]}"
    except Exception:
        pass
    return {"camera_name": CAMERA_ROW["name"], "device_id": DEVICE_ID,
            "logradouro": CAMERA_ROW["logradouro"], "bairro": CAMERA_ROW["bairro"],
            "rpa": CAMERA_ROW["rpa"], "horario_local": hh}


def gate_mids(win):
    n = len(win)
    mid_count = max(0, cfg.GEMINI_GATE_MID_FRAMES)
    if n < 3 or mid_count == 0:
        return None
    step = (n - 1) / (mid_count + 1)
    ks = sorted({int(round(step * (i + 1))) for i in range(mid_count)})
    ks = [k for k in ks if 0 < k < n - 1]
    return [win[k] for k in ks] or None


def build_window(frames):
    win = event_windows.subsample_frames(frames, cfg.GEMINI_CASCADE_MAX_FRAMES)
    win = event_windows.fit_frames_to_payload(win, cfg.GEMINI_MAX_PAYLOAD_BYTES)
    return win


def usage_tokens(usage):
    """(input, output_visivel, thinking). thinking_tokens são cobrados como OUTPUT
    (Gemini bilha thoughts_token_count na tarifa de output). Antes eu omitia o thinking
    -> custo subestimado; 2.5-flash pensa ~3k tok/ev e Gemini-3 idem."""
    thk = int(getattr(usage, "thinking_tokens", 0)
              or getattr(usage, "thoughts_token_count", 0) or 0)
    for a, b in (("input_tokens", "output_tokens"),
                 ("prompt_token_count", "candidates_token_count"),
                 ("prompt_tokens", "candidates_tokens")):
        i, o = getattr(usage, a, None), getattr(usage, b, None)
        if i is not None or o is not None:
            return int(i or 0), int(o or 0), thk
    return 0, 0, thk


def cost(model, tin, tout, tthink=0):
    p = PRICE.get(model)
    return (tin / 1e6 * p[0] + (tout + tthink) / 1e6 * p[1]) if p else 0.0


def call_backoff(fn, tries=5):
    for att in range(1, tries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa
            msg = str(exc)
            if not any(t in msg for t in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500")) or att == tries:
                raise
            time.sleep(min(90, 8 * 2 ** (att - 1)) * (0.7 + 0.6 * random.random()))


def run_one(ev, arm, dry):
    # Model is fixed at ARM level in main() (cfg.GEMINI_*_MODEL) to avoid a race
    # across threads; arms run sequentially. Do NOT mutate models here.
    spec = ARMS[arm]
    win = build_window(ev["frames"])
    cc = camera_context(win)
    rec = {"arm": arm, "event_id": ev["event_id"], "det_id": ev["det_id"],
           "category": ev["category"],
           "n_raw": len(ev["frames"]), "n_window": len(win),
           "gate_model": spec["gate"], "detail_model": spec["detail"],
           "gate_fire": "", "gate_conf": "", "disposal": "", "detail_conf": "",
           "waste_type": "", "tok_in": "", "tok_out": "", "tok_think": "",
           "cost_usd": 0.0, "latency_ms": "", "error": ""}
    if dry:
        rec["latency_ms"] = sum(p.stat().st_size for p in win)  # payload bytes
        return rec

    # ── CHAMADA ÚNICA: uma passada de detail na janela cheia, sem gate ──────────
    if spec.get("single"):
        win_s = even_subsample(win, spec["frames"]) if spec.get("frames") else win
        rec["n_window"] = len(win_s)
        try:
            t0 = time.time()
            d = call_backoff(lambda: analyze_with_gemini(
                image_paths=win_s, camera_context=cc, request_id=str(uuid4()),
                mosaic_mode=cfg.GEMINI_MOSAIC_AGENT2, prior_window_context=None,
                prompt_version=cfg.GEMINI_PROMPT_VERSION,
            ))
            dr = d.report
            di, do, dt = usage_tokens(d.usage)
            disp = int(bool(dr.infraction_confirmed))
            rec.update({"gate_fire": disp, "gate_conf": "", "disposal": disp,
                        "detail_conf": int(getattr(dr, "confidence_0_100", 0) or 0),
                        "waste_type": getattr(dr, "waste_type", "") or "",
                        "tok_in": di, "tok_out": do, "tok_think": dt,
                        "cost_usd": round(cost(spec["detail"], di, do, dt), 6),
                        "latency_ms": int((time.time() - t0) * 1000)})
        except Exception as exc:  # noqa
            rec["error"] = str(exc)[:300]
        return rec

    try:
        t0 = time.time()
        g = call_backoff(lambda: analyze_new_litter_with_gemini(
            first_frame=win[0], last_frame=win[-1],
            camera_context=cc, request_id=str(uuid4()), prior_window_context=None,
            use_mosaic=cfg.GEMINI_MOSAIC_AGENT1, mid_frames=gate_mids(win),
            prompt_version=cfg.GEMINI_PROMPT_VERSION,
        ))
        gr = g.report
        gi, go, gt = usage_tokens(g.usage)
        c = cost(spec["gate"], gi, go, gt)
        ti, to_, tt = gi, go, gt
        fire = bool(gr.new_litter_detected) and int(gr.confidence_0_100) >= TRIGGER_THR
        rec.update({"gate_fire": int(fire), "gate_conf": int(gr.confidence_0_100)})
        if fire:
            d = call_backoff(lambda: analyze_with_gemini(
                image_paths=win, camera_context=cc, request_id=str(uuid4()),
                mosaic_mode=cfg.GEMINI_MOSAIC_AGENT2, prior_window_context=None,
                prompt_version=cfg.GEMINI_PROMPT_VERSION,
            ))
            dr = d.report
            di, do, dt = usage_tokens(d.usage)
            c += cost(spec["detail"], di, do, dt)
            ti, to_, tt = ti + di, to_ + do, tt + dt
            rec.update({"disposal": int(bool(dr.infraction_confirmed)),
                        "detail_conf": int(getattr(dr, "confidence_0_100", 0) or 0),
                        "waste_type": getattr(dr, "waste_type", "") or ""})
        else:
            rec["disposal"] = 0
        rec.update({"tok_in": ti, "tok_out": to_, "tok_think": tt})
        rec["cost_usd"] = round(c, 6)
        rec["latency_ms"] = int((time.time() - t0) * 1000)
    except Exception as exc:  # noqa
        rec["error"] = str(exc)[:300]
    return rec


def append_csv(recs):
    cols = ["arm", "event_id", "det_id", "category", "n_raw", "n_window", "gate_model",
            "detail_model", "gate_fire", "gate_conf", "disposal", "detail_conf",
            "waste_type", "tok_in", "tok_out", "tok_think", "cost_usd", "latency_ms", "error"]
    new = not CSV_PATH.exists()
    if not new:  # trava: cabeçalho existente TEM que casar com cols (senão desalinha)
        existing = next(csv.reader(CSV_PATH.open(encoding="utf-8")), [])
        if existing and existing != cols:
            raise SystemExit(f"CSV {CSV_PATH.name} tem cabeçalho diferente ({len(existing)} col) "
                             f"do esperado ({len(cols)} col) — use --tag novo ou apague o arquivo.")
    with CSV_PATH.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        if new:
            w.writeheader()
        for r in recs:
            w.writerow(r)


def done_keys():
    if not CSV_PATH.exists():
        return set()
    return {(r["arm"], r["event_id"])
            for r in csv.DictReader(CSV_PATH.open(encoding="utf-8"))}


def aggregate():
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    out = {}
    for arm in sorted({r["arm"] for r in rows}):
        ar = [r for r in rows if r["arm"] == arm and not r["error"]]
        def frac(cat, field="disposal", val=1):
            sub = [r for r in ar if r["category"] == cat]
            hit = [r for r in sub if str(r.get(field)) == str(val)]
            return len(hit), len(sub)
        tp_fire, tp_n = frac("tp")
        fp_fire, fp_n = frac("fp")
        bl_fire, bl_n = frac("baseline")
        # DETECTION-level (prod-equivalent): a detection fires if ANY of its events fires.
        # Coalesced tails (no NEW litter) don't count against recall this way.
        def det_frac(cat):
            sub = [r for r in ar if r["category"] == cat]
            byd = {}
            for r in sub:
                byd.setdefault(r["det_id"], []).append(str(r.get("disposal")) == "1")
            fired = sum(1 for v in byd.values() if any(v))
            return fired, len(byd)
        tp_dfire, tp_dn = det_frac("tp")
        fp_dfire, fp_dn = det_frac("fp")
        costs = [float(r["cost_usd"]) for r in ar if r["cost_usd"]]
        lats = sorted(int(r["latency_ms"]) for r in ar if str(r.get("latency_ms")).isdigit())
        out[arm] = {
            "n": len(ar),
            # detection-level (primary — matches how prod creates one detection per event group)
            "tp_recall_det": round(100 * tp_dfire / tp_dn, 1) if tp_dn else None,
            "tp_det": f"{tp_dfire}/{tp_dn}",
            "fp_rate_det": round(100 * fp_dfire / fp_dn, 1) if fp_dn else None,
            "fp_det": f"{fp_dfire}/{fp_dn}",
            # event-level (secondary)
            "tp_recall_evt": round(100 * tp_fire / tp_n, 1) if tp_n else None,
            "tp_evt": f"{tp_fire}/{tp_n}",
            "fp_rate_evt": round(100 * fp_fire / fp_n, 1) if fp_n else None,
            "fp_evt": f"{fp_fire}/{fp_n}",
            "baseline_fire_rate": round(100 * bl_fire / bl_n, 1) if bl_n else None,
            "baseline": f"{bl_fire}/{bl_n}",
            "cost_per_event_usd": round(sum(costs) / len(costs), 6) if costs else None,
            "total_cost_usd": round(sum(costs), 4),
            "latency_p50_ms": lats[len(lats) // 2] if lats else None,
        }
    SUMMARY_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="current")
    ap.add_argument("--limit", type=int, default=None, help="first N events per category")
    ap.add_argument("--cats", default=None, help="comma list: tp,fp,indefinido,baseline")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--aggregate-only", action="store_true")
    ap.add_argument("--tag", default=None, help="sufixo do CSV (ex.: g3 -> bench_picam_g3.csv)")
    a = ap.parse_args()
    if a.tag:
        global CSV_PATH, SUMMARY_PATH
        CSV_PATH = RESULTS / f"bench_picam_{a.tag}.csv"
        SUMMARY_PATH = RESULTS / f"bench_picam_{a.tag}_summary.json"
    if a.aggregate_only:
        aggregate(); return
    arms = [x for x in a.arms.split(",") if x in ARMS]
    cats = a.cats.split(",") if a.cats else None
    events = load_events(a.limit, cats)
    done = set() if a.dry_run else done_keys()
    jobs = [(ev, arm) for arm in arms for ev in events if (arm, ev["event_id"]) not in done]
    print(f"arms={arms} events={len(events)} jobs={len(jobs)} "
          f"(skipped done={len(arms)*len(events)-len(jobs)}) dry={a.dry_run}")
    if a.dry_run:
        recs = [run_one(ev, arm, True) for ev, arm in jobs]
        import statistics
        for arm in arms:
            sub = [r for r in recs if r["arm"] == arm]
            wins = [r["n_window"] for r in sub]
            print(f"  [{arm}] windows med={int(statistics.median(wins))} "
                  f"min={min(wins)} max={max(wins)} | payload med={int(statistics.median(r['latency_ms'] for r in sub))//1024}KB")
        return
    # Arms run SEQUENTIALLY (model fixed per arm -> thread-safe within an arm).
    total = len(jobs)
    done_n = 0
    for arm in arms:
        spec = ARMS[arm]
        cfg.GEMINI_AGENT1_MODEL = spec["gate"]
        cfg.GEMINI_MODEL = spec["detail"]
        os.environ["GEMINI_AGENT1_MODEL"] = spec["gate"]
        os.environ["GEMINI_MODEL"] = spec["detail"]
        apply_arm_prompts(spec.get("prompt", "v1"))         # monkeypatch prompts (gate+detail)
        _G3_THINK["level"] = spec.get("think")               # thinking_level p/ Gemini-3
        _MEDIA_RES["res"] = spec.get("media")                # media_resolution p/ Gemini-3
        arm_jobs = [ev for ev2, arm2 in jobs if arm2 == arm for ev in [ev2]]
        print(f"=== arm {arm}: gate={spec['gate']} detail={spec['detail']} "
              f"prompt={spec.get('prompt','v1')} think={spec.get('think')} ({len(arm_jobs)} events) ===")
        buf = []
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futs = [pool.submit(run_one, ev, arm, False) for ev in arm_jobs]
            for fut in as_completed(futs):
                r = fut.result()
                done_n += 1
                buf.append(r)
                tag = "ERR" if r["error"] else f"gate={r['gate_fire']} disp={r['disposal']}"
                print(f"  [{done_n}/{total}] {r['arm']} {r['category']} {r['event_id']} {tag} {r['error'][:60]}")
                if len(buf) >= 5:
                    append_csv(buf); buf = []
        if buf:
            append_csv(buf)
    aggregate()


if __name__ == "__main__":
    main()
