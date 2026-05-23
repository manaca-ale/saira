"""Prompt V2 — behavioral discriminators for illegal-dumping detection.

V1 (current prompts) relied on scene_type + 2-of-3 boolean conditions (vehicle_stopped,
person_handling_material, new_ground_material). Field audit 2026-05-22 showed this
over-counts municipal collection (caminhão de coleta), pruning crews, and informal
recyclable collectors (carroceiros) — all of which satisfy all 3 booleans.

V2 distinguishes COLLECTION from DUMPING by BEHAVIOR + EQUIPMENT, not by uniform:
- material_flow_direction: "to_pile" (DUMPING) vs "from_pile" (COLLECTION)
- pile_volume_change: increased=DUMPING / decreased=COLLECTION / unchanged
- municipal_equipment_present: caminhão compactador EMLURB ONLY
  (NOT generic trucks/pickups, NOT uniform presence, NOT carroça)

NOTE on carroças (2026-05-22 patch): carroças used by catadores frequently
DUMP recyclable residuals on the ground after sorting. The 11 carroça events
in the official dataset are 9 Indefinido + 2 FP (zero clean TPs), so we no
longer treat a wooden carroça as municipal equipment. Carroceiro classification
falls out entirely from material_flow_direction + pile_volume_change.

Classification COLLECTION_OR_MAINTENANCE requires ≥2 corroborating behavioral
signals (uniforms never count). A camera-specific LOCAL_CONTEXT block is appended
when the camera has gemini_context_notes set, biasing the model toward expected
local patterns without changing thresholds globally.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

_NULL_LIKE = {
    "", "none", "null", "n/a", "na",
    "nao identificado", "nao visivel", "desconhecido", "unknown",
}


# =============================================================================
# Agent-1 (gate) — V2 system prompt
# =============================================================================
NEW_LITTER_SYSTEM_PROMPT_V2 = """
You analyze CCTV frames to classify urban scenes for illegal-dumping detection.
You receive 2-5 frames from the same camera in chronological order.

FIRST, classify scene_type as one of:
- EMPTY: No vehicles or people visible in any frame.
- TRAFFIC: Vehicles and/or people moving through the scene (different positions across frames).
- PARKED: Vehicles stationary but NO person actively handling material on the ground.
- DUMPING: A person/vehicle is ACTIVELY depositing material ON the ground (material moves
  FROM vehicle/person TO ground; pile of waste GROWS over the window).
- COLLECTION_OR_MAINTENANCE: People REMOVING material FROM the ground (carrying items
  from the pile to a vehicle/cart), OR a caminhão compactador EMLURB (large garbage
  truck with rear-loading hopper) is operating, OR a pruning crew is gathering
  vegetal waste with rakes/brooms/shovels. NOTE: a wooden carroça (catador cart)
  is NOT enough on its own — carroceiros both collect AND dump, so classify them
  by material_flow_direction and pile_volume_change, never by the cart itself.

IMPORTANT — over 95% of scenes are EMPTY, TRAFFIC, or PARKED. Default to these.

UNIFORM IS NOT A DISCRIMINATOR. Workers in any uniform (orange EMLURB vests,
construction-company shirts, mover jumpsuits, delivery uniforms) can be doing
EITHER legitimate collection OR illegal dumping. Decide by the BEHAVIOR (where the
material is going) and EQUIPMENT (specific municipal equipment vs generic vehicles),
NEVER by clothing alone.

EVALUATE each structured field INDEPENDENTLY based on visual evidence:

- vehicle_stopped: Is any vehicle stationary in 2+ frames?
- person_handling_material: Is a person carrying, unloading, or depositing material?
- new_ground_material: Is there material on the ground in the LAST frame that was
  absent in the FIRST frame? (specifically NEW material — not pre-existing piles)

- material_flow_direction: Dominant direction of material movement across the window:
  * "to_pile"   = material moves FROM vehicle/person TO the ground (DUMPING)
  * "from_pile" = material moves FROM the ground TO a vehicle/cart (COLLECTION)
  * "none"      = no material being moved
  * "ambiguous" = direction unclear (e.g., person holding bag but not moving it)

- pile_volume_change: Compare visible waste volume on the ground between first and
  last frame:
  * "increased"  = pile is visibly LARGER at the end (DUMPING signal)
  * "decreased"  = pile is visibly SMALLER at the end (COLLECTION signal)
  * "unchanged" = roughly the same (traffic, parking, transit)

- municipal_equipment_present: True ONLY if a caminhão compactador (large garbage
  truck with rear-loading hopper, often with EMLURB logo) is clearly visible.
  DO NOT mark true for: generic trucks, caminhonetes (Hilux/Strada/etc.),
  passenger cars, vans, uniformed workers without specific equipment, OR
  carroças (carroceiros are ambiguous — decide by flow direction and pile
  delta, never by the cart itself).

COMMON SCENES (these are NOT DUMPING — set new_litter_detected=false):
- Caminhão compactador EMLURB stopped, workers carrying bags FROM ground TO truck
  hopper, pile decreasing = COLLECTION_OR_MAINTENANCE.
- Pruning crew with rakes/brooms gathering branches from the ground = COLLECTION_OR_MAINTENANCE.
- Carroça de madeira with person sorting/loading recyclables AND pile clearly
  DECREASING across the window = COLLECTION_OR_MAINTENANCE.
  (If pile is UNCHANGED or INCREASING with a carroça present, treat as DUMPING
  or ambiguous — many carroceiros dump residuals after sorting.)
- Vehicles driving through, brief passenger pickup/dropoff = TRAFFIC.
- Parked cars with nobody handling material = PARKED.
- Pre-existing waste piles unchanged between frames = PARKED.
- Pedestrians walking through with bags but not depositing = TRAFFIC.
- Shadow/lighting changes between frames = EMPTY or TRAFFIC.

DUMPING SCENES (set new_litter_detected=true):
- Person carrying bags/material FROM a vehicle TO the ground, pile growing.
- Truck or caminhonete with raised cargo bed unloading debris on the ground.
- A construction/mover/cleaning worker in ANY uniform descarregando entulho de
  caminhonete para o chão (uniform does not exempt them — material direction
  determines the classification).

Set new_litter_detected=true ONLY when scene_type=DUMPING.
For EMPTY/TRAFFIC/PARKED/COLLECTION_OR_MAINTENANCE: new_litter_detected=false,
confidence_0_100=0.

Respond with ONLY valid JSON.
""".strip()


# =============================================================================
# Agent-2 (detail) — V2 system prompt
# =============================================================================
SYSTEM_PROMPT_V2 = """
Voce e um auditor visual de descarte irregular de residuos em via publica no Brasil.
Responda APENAS JSON valido com os campos solicitados.

BASELINE ESPERADO: A cena padrao consiste em via asfaltada, calcadas, veiculos
estacionados, infraestrutura municipal fixa (postes, lixeiras com tampa, bollards,
marcacoes viarias) e iluminacao natural variavel. Estes elementos sao NORMAIS.

PROCESSO DE VERIFICACAO (siga na ordem):
1. INVENTARIO: Em baseline_description, liste ate 5 objetos fixos no primeiro frame.
2. DELTA TEMPORAL: Identifique o que MUDOU entre o primeiro e o ultimo frame.
3. DIRECAO DO MATERIAL: O material esta indo DO veiculo/pessoa PARA o chao
   (DESCARTE), ou DO chao PARA o veiculo/carroca (COLETA)?
4. CLASSIFICACAO: SOMBRA_ILUMINACAO, OBJETO_EM_MOVIMENTO, COMPORTAMENTO_DESCARTE,
   ou COMPORTAMENTO_COLETA.
5. DECISAO: infraction_confirmed=true APENAS quando houver COMPORTAMENTO_DESCARTE
   confirmado pela direcao do material.

ATIVIDADES QUE NAO SAO DESCARTE (infraction_confirmed=false):
- Coleta municipal: caminhao COMPACTADOR (com hopper traseiro caracteristico
  EMLURB) parado, pessoas levando sacos DO CHAO PARA o caminhao. Pilha DIMINUI.
- Poda da prefeitura: equipe usando vassouras, ancinhos e pas para JUNTAR e
  RECOLHER restos vegetais. Material vai do chao para uma pilha organizada ou
  para um caminhao.
- Catador/carroceiro COLETANDO: pessoa com carroca de madeira revirando material
  e levando reciclaveis DO CHAO PARA a carroca, com a PILHA DIMINUINDO ao longo
  da janela. So conta como coleta quando o saldo final no chao e MENOR.
  ATENCAO: se o carroceiro DEIXOU restos novos no chao (pilha cresceu ou
  surgiram sacos novos), isso e DESCARTE, nao coleta. Carroceiros tambem
  descartam — decisao sai pela direcao do material, nunca pela presenca
  da carroca.

ATIVIDADES QUE SAO DESCARTE (infraction_confirmed=true):
- Material novo claramente visivel no chao que surgiu durante a sequencia E
  veio de um veiculo, carrinho ou pessoa parada na cena.
- Veiculo PARADO com cacamba aberta/levantada descarregando entulho no chao.
- Pessoa(s) ESTACIONARIA(s) levando sacos/objetos DO veiculo PARA o chao,
  inclusive se estiverem uniformizadas (construtora, mudanceira, limpeza
  privada). UNIFORME NAO ISENTA DESCARTE.

DISCRIMINADOR PRIMARIO — DIRECAO DO MATERIAL:
- material indo DO veiculo/pessoa PARA o chao = DESCARTE
- material indo DO chao PARA o veiculo/carroca = COLETA
- pilha DIMINUI entre primeiro e ultimo frame = COLETA
- pilha AUMENTA entre primeiro e ultimo frame = DESCARTE

DISCRIMINADOR SECUNDARIO — EQUIPAMENTO:
- caminhao compactador EMLURB (hopper traseiro grande) = COLETA municipal
- carroca de madeira (cavalo ou tracao humana) = NEUTRO (carroceiros tanto
  coletam quanto descartam — decisao SEMPRE pela direcao do material e
  delta da pilha, nunca pela carroca em si)
- caminhonete particular (Hilux/Strada/etc.), van, carro de passeio = NEUTRO
  (decisao depende da direcao do material)

SINAL-CHAVE: veiculos e pessoas que descartam ficam ESTACIONARIOS por varios
frames durante a acao. Trafego normal mostra posicoes diferentes entre frames.

Quando infraction_confirmed=true, inclua bounding boxes normalizados 0-1000
[y_min, x_min, y_max, x_max]:
- waste_bbox: delimitando o residuo depositado (quando visivel como objeto distinto)
- offender_bbox: delimitando o infrator/veiculo (quando visivel)
Quando o material depositado se mistura a uma pilha existente, waste_bbox pode
ser null desde que offender_bbox identifique o agente do descarte.

Uso correto de lixeira publica e comportamento cidadao correto — infraction_confirmed=false.
Veiculos parando para embarque/desembarque de passageiros e transporte urbano normal.
waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_detected descreve somente a capacidade de identificar o autor/veiculo.
Se um campo nao puder ser inferido com seguranca, retorne null.
""".strip()


# =============================================================================
# Extended Pydantic schemas
# =============================================================================
class GeminiNewLitterReportV2(BaseModel):
    """V2: extends V1 with material_flow_direction, pile_volume_change, and
    municipal_equipment_present fields used to distinguish DUMPING from COLLECTION."""

    scene_type: str = Field(
        description=(
            "Classify: EMPTY, TRAFFIC, PARKED, DUMPING, or COLLECTION_OR_MAINTENANCE."
        ),
    )

    # Original 3 booleans (kept for backward compatibility with gate logic).
    vehicle_stopped: bool = Field(default=False)
    person_handling_material: bool = Field(default=False)
    new_ground_material: bool = Field(default=False)

    # V2 behavioral discriminators.
    material_flow_direction: str = Field(
        default="none",
        description="to_pile (DUMPING) | from_pile (COLLECTION) | none | ambiguous",
    )
    pile_volume_change: str = Field(
        default="unchanged",
        description="increased (DUMPING) | decreased (COLLECTION) | unchanged",
    )
    municipal_equipment_present: bool = Field(
        default=False,
        description=(
            "True ONLY for caminhao compactador OR carroca de madeira. "
            "NOT true for generic trucks, pickups, or uniformed workers."
        ),
    )

    new_litter_detected: bool
    confidence_0_100: int = Field(ge=0, le=100)
    evidence_summary: str = Field(min_length=1, max_length=500)
    first_frame_has_litter: bool = False
    last_frame_has_litter: bool = False
    waste_type: Optional[str] = Field(default=None, max_length=100)
    raw_reason_codes: Optional[list[str]] = Field(default=None)
    scene_delta_analysis: str = Field(default="", max_length=500)

    @field_validator("waste_type", mode="before")
    @classmethod
    def _normalize_waste(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if text.lower() in _NULL_LIKE:
            return None
        return text

    @field_validator("material_flow_direction", mode="before")
    @classmethod
    def _normalize_flow(cls, value: object) -> str:
        if value is None:
            return "none"
        s = str(value).strip().lower()
        if s in ("to_pile", "to pile", "topile", "dumping"):
            return "to_pile"
        if s in ("from_pile", "from pile", "frompile", "collection"):
            return "from_pile"
        if s in ("ambiguous", "unclear", "mixed"):
            return "ambiguous"
        return "none"

    @field_validator("pile_volume_change", mode="before")
    @classmethod
    def _normalize_pile(cls, value: object) -> str:
        if value is None:
            return "unchanged"
        s = str(value).strip().lower()
        if s in ("increased", "increase", "grew", "larger", "bigger"):
            return "increased"
        if s in ("decreased", "decrease", "shrunk", "smaller", "reduced"):
            return "decreased"
        return "unchanged"

    @field_validator("scene_type", mode="before")
    @classmethod
    def _normalize_scene(cls, value: object) -> str:
        if value is None:
            return "EMPTY"
        s = str(value).strip().upper()
        return s if s in {"EMPTY", "TRAFFIC", "PARKED", "DUMPING", "COLLECTION_OR_MAINTENANCE"} else s

    @field_validator("raw_reason_codes", mode="before")
    @classmethod
    def _normalize_codes(cls, value: object) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, list):
            r = [str(i).strip() for i in value if str(i).strip()]
            return r or None
        if isinstance(value, str):
            t = value.strip()
            return [t] if t else None
        return None


# =============================================================================
# User-prompt builders with LOCAL_CONTEXT block
# =============================================================================
def build_v2_user_prompt_gate(
    first_frame_name: str,
    last_frame_name: str,
    camera_context: Optional[dict[str, str]] = None,
    prior_window_context: Optional[str] = None,
    mosaic: bool = False,
    mid_frame_names: Optional[list[str]] = None,
) -> str:
    """V2 user prompt for Agent-1 (gate). Adds LOCAL_CONTEXT and pile-delta question."""
    context_lines = []
    local_notes = ""
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                local_notes = str(value).strip()
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    local_block = ""
    if local_notes:
        local_block = f"\nLOCAL_CONTEXT (this specific camera's known patterns):\n{local_notes}\n"

    mid_block = ""
    if mid_frame_names:
        labels = ", ".join(mid_frame_names)
        mid_block = f"Mid-window frames (25%/50%/75%): {labels}\n"

    json_fields = (
        "Return JSON with: scene_type, vehicle_stopped, person_handling_material, "
        "new_ground_material, material_flow_direction, pile_volume_change, "
        "municipal_equipment_present, new_litter_detected, confidence_0_100, "
        "evidence_summary, first_frame_has_litter, last_frame_has_litter, "
        "waste_type, raw_reason_codes, scene_delta_analysis.\n"
    )

    explicit_question = (
        "Compare the FIRST and LAST frame:\n"
        "1. Did the visible waste pile on the ground INCREASE, DECREASE, or stay roughly the same?\n"
        "2. Is the dominant material movement going TO the ground (dumping) or FROM the ground (collection)?\n"
        "3. Is a caminhao compactador (rear-hopper municipal truck) OR a wooden carroca clearly visible?\n"
    )

    if mosaic:
        frame_desc = (
            f"The image provided is a side-by-side composite: "
            f"LEFT = initial frame ({first_frame_name}), RIGHT = final frame ({last_frame_name}). "
            "Compare the left half vs the right half."
        )
        return (
            f"{frame_desc}\n"
            f"{mid_block}"
            f"{explicit_question}"
            f"{json_fields}"
            f"{prior_block}"
            f"{local_block}"
            "Camera context:\n"
            f"{context_block}"
        )

    frame_lines = (
        f"Initial frame: {first_frame_name}\n"
        f"Final frame: {last_frame_name}\n"
        f"{mid_block}"
    )
    return (
        f"{frame_lines}"
        f"{explicit_question}"
        "If a mid-window frame is provided, also check for Pattern C (ghost events).\n"
        f"{json_fields}"
        f"{prior_block}"
        f"{local_block}"
        "Camera context:\n"
        f"{context_block}"
    )


def build_v2_user_prompt_detail(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> str:
    """V2 user prompt for Agent-2 (detail). Adds LOCAL_CONTEXT block."""
    context_lines = []
    local_notes = ""
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                local_notes = str(value).strip()
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    local_block = ""
    if local_notes:
        local_block = f"\nLOCAL_CONTEXT (this specific camera's known patterns):\n{local_notes}\n"

    if mosaic_mode != "off":
        if mosaic_mode == "4x3":
            frame_desc = (
                "The image(s) provided are a 4-row x 3-column mosaic grid of frames "
                "numbered 1-12 (left-to-right, top-to-bottom, chronological order). "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        else:  # 3x2split
            frame_desc = (
                "Two mosaic images are provided: the first contains frames 1-6 "
                "(3 columns x 2 rows, chronological), the second contains frames 7-12. "
                "Frame 1 is earliest, frame 12 is latest. "
                "Use 'frame_N' (e.g. 'frame_7') as event_frame_name and offender_frame_name."
            )
        return (
            "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
            "1) confirmacao de infracao (infraction_confirmed)\n"
            "2) confianca 0..100\n"
            "3) resumo factual curto da evidencia\n"
            "4) classificacao de residuo/material e volume aproximado\n"
            "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
            "6) event_frame_name e offender_frame_name usando o formato 'frame_N'\n"
            "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
            "Discriminador chave: material indo PARA o chao = DESCARTE; material indo DO chao = COLETA.\n"
            f"Formato das imagens: {frame_desc}\n"
            f"{prior_block}"
            f"{local_block}"
            "Contexto da camera:\n"
            f"{context_block}"
        )

    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens e retorne JSON estruturado com:\n"
        "1) confirmacao de infracao (infraction_confirmed)\n"
        "2) confianca 0..100\n"
        "3) resumo factual curto da evidencia\n"
        "4) classificacao de residuo/material e volume aproximado\n"
        "5) dados de infrator e dados veiculares quando visiveis (opcional)\n"
        "6) event_frame_name e offender_frame_name escolhidos somente dentre os nomes permitidos\n"
        "Regra de decisao: infraction_confirmed=true pode ocorrer mesmo com offender_detected=false.\n"
        "Discriminador chave: material indo PARA o chao = DESCARTE; material indo DO chao = COLETA.\n"
        f"Nomes de frame permitidos: {frame_block}\n"
        f"{prior_block}"
        f"{local_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )


# =============================================================================
# Deterministic gate V2 — behavioral signals + uniform-independent overrides
# =============================================================================
def apply_v2_gates(report: GeminiNewLitterReportV2, request_id: Optional[str] = None) -> tuple[GeminiNewLitterReportV2, bool]:
    """Apply the V2 deterministic gate to a fresh Agent-1 report.

    Returns (report, is_maintenance) where:
    - report has been mutated to enforce the gate decisions
    - is_maintenance=True signals the caller should activate the cooldown
    """
    import logging
    logger = logging.getLogger(__name__)

    scene = (report.scene_type or "").upper().strip()
    flow = report.material_flow_direction
    pile = report.pile_volume_change
    has_munic_equip = bool(report.municipal_equipment_present)

    # Count corroborating behavioral signals for COLLECTION_OR_MAINTENANCE.
    # Uniform NEVER counts. We need >=2 of these 3 to accept a collection
    # classification and trigger cooldown.
    maintenance_signals = 0
    if flow == "from_pile":
        maintenance_signals += 1
    if has_munic_equip:
        maintenance_signals += 1
    if pile == "decreased":
        maintenance_signals += 1

    is_maintenance = False

    if scene == "COLLECTION_OR_MAINTENANCE":
        if maintenance_signals >= 2:
            # Strong evidence: suppress + trigger cooldown.
            report.new_litter_detected = False
            report.confidence_0_100 = 0
            is_maintenance = True
            logger.info(
                "v2_gate_maintenance_confirmed: signals=%d (flow=%s, equip=%s, pile=%s) request_id=%s",
                maintenance_signals, flow, has_munic_equip, pile, request_id,
            )
        else:
            # Model labelled COLLECTION but evidence is thin — downgrade to PARKED
            # and let normal pipeline decide. NO cooldown.
            report.scene_type = "PARKED"
            scene = "PARKED"
            logger.info(
                "v2_gate_maintenance_downgraded: signals=%d (<2) -> PARKED, no cooldown request_id=%s",
                maintenance_signals, request_id,
            )

    # Blind rule: pile decreasing is NEVER dumping.
    if pile == "decreased" and report.new_litter_detected:
        logger.info(
            "v2_gate_pile_decreasing: forcing new_litter_detected=false request_id=%s",
            request_id,
        )
        report.new_litter_detected = False
        report.confidence_0_100 = 0

    # Positive override: material flowing TO ground + pile increasing = DUMPING
    # regardless of scene_type (covers e.g. construction worker with uniform
    # offloading debris from a Hilux — must not be suppressed by uniform).
    if flow == "to_pile" and pile == "increased" and not report.new_litter_detected:
        logger.info(
            "v2_gate_positive_override: flow=to_pile + pile=increased -> forcing new_litter_detected=true request_id=%s",
            request_id,
        )
        report.new_litter_detected = True
        report.confidence_0_100 = max(report.confidence_0_100, 85)
        report.scene_type = "DUMPING"
        is_maintenance = False  # never trigger cooldown when we are dumping

    # Hard gate: only DUMPING can trigger.
    if (report.scene_type or "").upper().strip() != "DUMPING" and report.new_litter_detected:
        logger.info(
            "v2_gate_scene_not_dumping: scene=%s -> forcing new_litter_detected=false request_id=%s",
            report.scene_type, request_id,
        )
        report.new_litter_detected = False
        report.confidence_0_100 = 0

    return report, is_maintenance
