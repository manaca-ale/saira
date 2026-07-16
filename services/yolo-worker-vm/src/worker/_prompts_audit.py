"""Prompt AUDIT — Agent-2 (Detail) como auditor crítico do gate.

Hoje o Agent-2 (SYSTEM_PROMPT V1 em detector_gemini.py) atua como CONFIRMADOR
do gate: o framing assume que o gate identificou descarte correto e a tarefa
é detalhar resíduo/infrator/veículo. Quando o gate dispara em FP (pessoas
passando, coleta EMLURB, chuva, etc), o Detail tende a só confirmar.

V_AUDIT muda a postura para AUDITOR ADVERSARIAL:
- Texto explícito: "Suponha que o gate pode ter falhado. Verifique
  INDEPENDENTEMENTE."
- Checklist de 8 padrões de FP do dataset oficial; se cena bate, force
  infraction_confirmed=false.
- Schema com campo enum `fp_pattern_match` obrigatório:
  - "real_dumping"        → descarte real
  - "traffic_passing"     → pessoas/veículos passando, postura passing_by
  - "municipal_collection"→ caminhão EMLURB recolhendo, pile decreasing
  - "pruning_crew"        → equipe de poda com rakes/vassouras
  - "carroceiro_sorting"  → carroça com pessoas sortendo recicláveis
  - "rain_blur"           → chuva ou mudanças de iluminação
  - "parking_dropoff"     → carro estacionou (passageiro/criança), sem objeto
  - "other"               → cena não classificável

apply_audit_consistency() FORÇA infraction_confirmed=false se
fp_pattern_match != "real_dumping". Isso evita a contradição interna onde
o modelo nomeia o FP corretamente mas confirma infração mesmo assim.

Spike target (camp 15 replay): reduzir FP rate do Detail em ≥50% sem perder TPs.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .schemas_gemini import GeminiInfractionReport

logger = logging.getLogger(__name__)


VALID_FP_PATTERNS = {
    "real_dumping",
    "traffic_passing",
    "municipal_collection",
    "pruning_crew",
    "carroceiro_sorting",
    "rain_blur",
    "parking_dropoff",
    "other",
}

# AUDIT_V2 (camp 15b, 2026-05-23) — relaxed version after camp 15 V1 audit
# killed 7/8 TPs. Only patterns that are UNAMBIGUOUSLY non-infraction get
# deterministically forced to false here. carroceiro_sorting and other are
# left to the model's judgement because:
#   - carroceiro_sorting can be a real infraction when the catador is
#     actively depositing (cart presence alone shouldn't disqualify)
#   - other is the model's "uncertain" bucket; forcing false there was the
#     single biggest TP-killer in camp 15 (3/7 lost TPs landed in "other")
V2_FORCE_FALSE_PATTERNS = {
    "traffic_passing",
    "municipal_collection",
    "pruning_crew",
    "rain_blur",
    "parking_dropoff",
}

_FP_PATTERN_ALIASES = {
    # Common variants the model might produce
    "dumping": "real_dumping",
    "descarte": "real_dumping",
    "passing": "traffic_passing",
    "passing_by": "traffic_passing",
    "traffic": "traffic_passing",
    "passantes": "traffic_passing",
    "collection": "municipal_collection",
    "coleta": "municipal_collection",
    "emlurb": "municipal_collection",
    "compactador": "municipal_collection",
    "pruning": "pruning_crew",
    "poda": "pruning_crew",
    "limpeza": "pruning_crew",
    "carroceiro": "carroceiro_sorting",
    "carroca": "carroceiro_sorting",
    "catador": "carroceiro_sorting",
    "rain": "rain_blur",
    "chuva": "rain_blur",
    "shadow": "rain_blur",
    "sombra": "rain_blur",
    "parking": "parking_dropoff",
    "estacionamento": "parking_dropoff",
    "dropoff": "parking_dropoff",
    "passageiro": "parking_dropoff",
}


SYSTEM_PROMPT_AUDIT = """
Voce e um AUDITOR INDEPENDENTE de descarte irregular de residuos em via publica.
Recebe imagens que o sistema de triagem (Agent-1) classificou como SUSPEITAS,
mas voce NAO confia nessa classificacao. Faca um exame independente.

POSTURA: assume que o triador pode ter cometido FALSO POSITIVO. So confirme
infraction_confirmed=true se houver EVIDENCIA CLARA de descarte real.

=============================================================================
PADRAO 1 — IDENTIFIQUE PRIMEIRO O TIPO DE CENA
=============================================================================

Antes de decidir, classifique a cena em UM dos 8 padroes abaixo (campo
fp_pattern_match no JSON):

a) "real_dumping" — DESCARTE REAL irregular
   Sinais OBRIGATORIOS: pessoa em postura de deposito (inclinada/agachada
   junto a pilha com objeto nas maos em algum frame E maos vazias/diferentes
   em outro frame), OU veiculo parado com cacamba aberta descarregando
   entulho no chao. So escolha este se voce CONSEGUE descrever em palavras
   o momento exato do deposito visivel nos frames.

b) "traffic_passing" — pedestres ou veiculos atravessando a cena
   Sinais: pessoas em posicoes DIFERENTES entre frames (trajetoria reta),
   nao param junto da pilha por 2+ frames consecutivos. Pode ter pessoa
   visivel proximo a pilha em UM frame, mas nao em multiplos.

c) "municipal_collection" — coleta da prefeitura
   Sinais: caminhao COMPACTADOR EMLURB (hopper traseiro caracteristico)
   parado com pessoas levando sacos DO CHAO PARA o caminhao; ou pilha
   visivelmente DIMINUI entre primeiro e ultimo frame; ou caminhao
   basculante recolhendo entulho.

d) "pruning_crew" — equipe de poda municipal
   Sinais: pessoas usando vassouras/ancinhos/pas para juntar restos
   vegetais; uniformes verdes ou laranjas EMLURB; presenca de galhos/folhas
   sendo organizados em pilha para retirada.

e) "carroceiro_sorting" — catador com carroca de madeira
   Sinais: carroca de madeira visivel (puxada por cavalo ou a mao);
   pessoas mexendo na carroca e/ou na pilha sem postura clara de
   deposito; pilha pode crescer ou diminuir.

f) "rain_blur" — chuva ou mudanca de iluminacao
   Sinais: borroes verticais na imagem (chuva), mudanca de luminosidade
   entre frames (sol/nuvens/sombras de arvores), nenhuma pessoa visivel
   na zona da pilha.

g) "parking_dropoff" — carro estacionou rapido
   Sinais: veiculo para por 1-2 frames, pessoas SAEM do veiculo (nao
   carregando objetos visiveis) e se afastam para outra direcao (nao
   para pilha).

h) "other" — nenhuma das acima ou cena verdadeiramente ambigua

=============================================================================
PADRAO 2 — DECISAO DE INFRACAO
=============================================================================

infraction_confirmed=true APENAS quando fp_pattern_match="real_dumping".
Para qualquer outro padrao, set infraction_confirmed=false E
confidence_0_100=0.

NUNCA confirme infracao sem conseguir DESCREVER textualmente:
- Onde a pessoa estava (posicao no frame)
- O que ela carregava (saco/objeto/cor)
- Em qual frame especifico o deposito ocorreu
- Para onde ela foi depois (saiu da cena? ficou? sumiu de vista?)

Se voce NAO consegue responder essas 4 perguntas, fp_pattern_match deve
ser "other" e infraction_confirmed=false.

=============================================================================
CASOS LIMITROFES — quando em duvida, escolha NAO-DESCARTE
=============================================================================

- Pessoa em pe perto da pilha, sem bending claro → "traffic_passing"
- Pessoa atravessando com saco mas nao parou na pilha → "traffic_passing"
- Carroca presente mas pilha unchanged → "carroceiro_sorting"
- Uniforme EMLURB visivel mas postura ambigua → AVALIE PELA DIRECAO DO
  MATERIAL (chao→caminhao = collection; caminhao→chao = real_dumping)
- Borroes/sombras sem pessoa → "rain_blur"
- Cao/passaros/bicicleta sozinhos → "traffic_passing"

UNIFORME NAO E DISCRIMINADOR. Trabalhador uniformizado pode estar
COLETANDO ou DESCARTANDO. Decida pela direcao do material e postura.

=============================================================================
DESCARTE PEDESTRE — cuidado com volumetria invisivel
=============================================================================

Descartes pedestres reais (0.01-0.15 m³, 1 saco) sao INVISIVEIS na
resolucao da camera — first frame parece igual a last frame mesmo
com descarte. Para esses casos, o sinal e POSTURA + TRAJETORIA:
- Pessoa inclinada/agachada PERTO da pilha em 2+ frames consecutivos,
- COM objeto nas maos em pelo menos 1 frame,
- E maos vazias OU diferente material em frame posterior.

Se NAO consegue verificar essas 3 condicoes, NAO classifique como
real_dumping. Prefira "other" ou "traffic_passing".

=============================================================================
FORMATO DO JSON
=============================================================================

Alem dos campos usuais do GeminiInfractionReport (waste_type, offender_*,
vehicle_*, bounding boxes), inclua:

- fp_pattern_match: um dos 8 valores acima (OBRIGATORIO).
- audit_rationale: 1-2 frases explicando por que voce escolheu esse padrao
  (em portugues). Mencione o frame especifico se relevante.

Quando infraction_confirmed=true, inclua bounding boxes 0-1000 normalizados:
- waste_bbox: delimitando o residuo depositado (quando visivel como objeto distinto)
- offender_bbox: delimitando o infrator/veiculo (quando visivel)

waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_types: lista com um ou mais valores dentre: pessoa, carro, caminhao, moto, carroca, bicicleta, outro.
Se nao puder inferir um campo com seguranca, retorne null.
Responda APENAS JSON valido.
""".strip()


SYSTEM_PROMPT_AUDIT_V2 = """
Voce e um AUDITOR INDEPENDENTE de descarte irregular de residuos em via publica.
Recebe imagens que o sistema de triagem (Agent-1) classificou como SUSPEITAS.
Faca um exame CRITICO mas JUSTO: nem todo gate-hit e descarte real, mas
descartes pedestres reais sao SUTIS — pessoa inclinada perto da pilha com
um saco pode ser TP mesmo sem volumetria grande.

=============================================================================
PADRAO 1 — CLASSIFIQUE A CENA EM UM DOS 8 TIPOS (fp_pattern_match)
=============================================================================

a) "real_dumping" — DESCARTE REAL irregular
   Sinais: pessoa em postura de DEPOSITO (inclinada/agachada junto a pilha,
   com objeto/saco visivel em algum frame) OU veiculo com cacamba aberta
   descarregando entulho. Postura > volumetria — pequenos descartes pedestres
   (1 saco, 0.01-0.15 m3) sao INVISIVEIS na resolucao da camera.

b) "traffic_passing" — pedestres/veiculos atravessando, NAO param na pilha
   Sinais: pessoas em posicoes DIFERENTES entre frames (trajetoria reta),
   NAO ficam estacionarias proximas a pilha. Veiculos passando em movimento.

c) "municipal_collection" — coleta da prefeitura
   Sinais: caminhao COMPACTADOR EMLURB (hopper traseiro) parado com pessoas
   levando sacos DO CHAO PARA o caminhao; OU pilha visivelmente DIMINUI
   entre primeiro e ultimo frame; OU caminhao basculante recolhendo entulho.

d) "pruning_crew" — equipe de poda municipal
   Sinais: pessoas com vassouras/ancinhos/pas juntando restos vegetais;
   uniformes EMLURB (verde/laranja); galhos/folhas sendo organizados.

e) "carroceiro_sorting" — catador com carroca de madeira
   Sinais OBRIGATORIOS: carroca de madeira VISIVEL (puxada por cavalo ou
   a mao). IMPORTANTE: presenca de carroca NAO elimina infracao — se o
   catador estiver visivelmente DEPOSITANDO material (postura de deposito,
   saco que some entre frames), continua sendo descarte irregular. Use
   esta categoria SO se nao houver postura clara de deposito.

f) "rain_blur" — chuva ou mudanca brusca de iluminacao
   Sinais: borroes verticais (chuva), mudanca de luminosidade brusca,
   nenhuma pessoa visivel na zona da pilha.

g) "parking_dropoff" — carro estacionou brevemente
   Sinais: veiculo para por 1-2 frames, pessoas SAEM do veiculo SEM objetos
   visiveis e se afastam para outra direcao (nao para pilha).

h) "other" — cena que nao se encaixa claramente nas 7 acima

=============================================================================
PADRAO 2 — DECISAO DE INFRACAO (REGRA REVISADA V2)
=============================================================================

infraction_confirmed=false OBRIGATORIO quando fp_pattern_match ∈
{traffic_passing, municipal_collection, pruning_crew, rain_blur,
parking_dropoff}. Estes 5 sao FPs inequivocos.

Para fp_pattern_match ∈ {real_dumping, carroceiro_sorting, other}: voce
DECIDE com base na evidencia visual. Confirme infracao APENAS se:
- ha pessoa com postura de deposito (inclinada/agachada perto da pilha,
  COM objeto/saco em pelo menos UM frame), OU
- ha veiculo PARADO com material saindo da cacamba/porta-malas para o chao.

Para "other": prefira confirmar se voce realmente VE a acao de deposito,
mesmo que sem todos os detalhes. NAO use "other" como default por seguranca
— se a evidencia e fraca, prefira "traffic_passing" (se ha pessoas passando)
ou "real_dumping" + confidence baixa (se ha sinal mas voce tem duvidas).

=============================================================================
DESCARTE PEDESTRE — cuidado com volumetria invisivel
=============================================================================

Pequenos descartes pedestres (1 saco) sao INVISIVEIS frame-a-frame —
first frame parece igual a last frame. Para esses casos, o sinal e:
- postura inclinada/agachada perto da pilha,
- saco/objeto visivel em pelo menos 1 frame,
- pessoa pode permanecer perto da pilha por 2+ frames (sorting) OU sair
  rapido (drop-and-go).

NAO desclassifique TPs sutis para "other" por seguranca. Se voce VE alguem
com postura de deposito perto da pilha, e provavelmente real_dumping.

UNIFORME NAO E DISCRIMINADOR. Trabalhador uniformizado pode estar
COLETANDO ou DESCARTANDO. Decida pela direcao do material:
- material indo do CHAO para CAMINHAO/carroca = collection/sorting
- material vindo de SACO/CACAMBA para o CHAO = real_dumping

=============================================================================
FORMATO DO JSON
=============================================================================

Alem dos campos usuais do GeminiInfractionReport, inclua:
- fp_pattern_match: um dos 8 valores (OBRIGATORIO).
- audit_rationale: 1-2 frases em pt-BR explicando a escolha do padrao
  e da decisao de infracao.

Quando infraction_confirmed=true, inclua bounding boxes 0-1000:
- waste_bbox: residuo depositado (quando visivel como objeto distinto)
- offender_bbox: infrator/veiculo (quando visivel)

waste_type: Entulho, Lixo domiciliar, Poda, ou Plastico.
offender_types: lista com um ou mais valores dentre: pessoa, carro, caminhao, moto, carroca, bicicleta, outro.
Se nao puder inferir um campo com seguranca, retorne null.
Responda APENAS JSON valido.
""".strip()


# =============================================================================
# Extended Pydantic schema — adds fp_pattern_match + audit_rationale.
# =============================================================================
class GeminiInfractionReportAudit(GeminiInfractionReport):
    """V_AUDIT extends the base V1 detail report with FP pattern classification."""

    fp_pattern_match: str = Field(
        default="other",
        description=(
            "FP pattern category: real_dumping, traffic_passing, municipal_collection, "
            "pruning_crew, carroceiro_sorting, rain_blur, parking_dropoff, or other."
        ),
    )
    audit_rationale: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Brief justification for the fp_pattern_match choice.",
    )

    @field_validator("fp_pattern_match", mode="before")
    @classmethod
    def _normalize_fp_pattern(cls, value: object) -> str:
        if value is None:
            return "other"
        s = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        if s in VALID_FP_PATTERNS:
            return s
        if s in _FP_PATTERN_ALIASES:
            return _FP_PATTERN_ALIASES[s]
        # Try fuzzy: contains any keyword
        for key, target in _FP_PATTERN_ALIASES.items():
            if key in s:
                return target
        return "other"


# =============================================================================
# User-prompt builder — same shape as V1 detail prompt, with explicit
# request for fp_pattern_match.
# =============================================================================
def build_audit_user_prompt(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> str:
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    json_fields_extra = (
        "INCLUA NO JSON estes campos extras: fp_pattern_match (um de: real_dumping, "
        "traffic_passing, municipal_collection, pruning_crew, carroceiro_sorting, "
        "rain_blur, parking_dropoff, other) E audit_rationale (1-2 frases em pt-BR).\n"
        "REGRA: se fp_pattern_match != real_dumping, infraction_confirmed DEVE ser false.\n"
    )

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
            "Analise a sequencia temporal de imagens como AUDITOR INDEPENDENTE do gate.\n"
            "Primeiro classifique a cena em um dos 8 padroes (fp_pattern_match).\n"
            "So confirme infraction_confirmed=true se fp_pattern_match=real_dumping.\n"
            f"{json_fields_extra}"
            f"Formato das imagens: {frame_desc}\n"
            f"{prior_block}"
            "Contexto da camera:\n"
            f"{context_block}"
        )

    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens como AUDITOR INDEPENDENTE do gate.\n"
        "Primeiro classifique a cena em um dos 8 padroes (fp_pattern_match).\n"
        "So confirme infraction_confirmed=true se fp_pattern_match=real_dumping.\n"
        f"{json_fields_extra}"
        f"Nomes de frame permitidos: {frame_block}\n"
        f"{prior_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )


# =============================================================================
# Deterministic consistency check — apply after model returns.
# =============================================================================
def apply_audit_consistency(report: GeminiInfractionReportAudit,
                            request_id: Optional[str] = None) -> GeminiInfractionReportAudit:
    """If fp_pattern_match != real_dumping but infraction_confirmed=True,
    force infraction_confirmed=False. Catches the contradiction where the
    model correctly names the FP but still confirms infraction.
    """
    pattern = report.fp_pattern_match or "other"
    if report.infraction_confirmed and pattern != "real_dumping":
        logger.info(
            "audit_consistency: fp_pattern_match=%s contradicts infraction_confirmed=true "
            "-> forcing false (request_id=%s)",
            pattern, request_id,
        )
        report.infraction_confirmed = False
        report.confidence_0_100 = 0
    return report


# =============================================================================
# AUDIT_V2 — relaxed user-prompt builder + consistency check.
# =============================================================================
def build_audit_v2_user_prompt(
    camera_context: Optional[dict[str, str]] = None,
    frame_names: Optional[list[str]] = None,
    mosaic_mode: str = "off",
    prior_window_context: Optional[str] = None,
) -> str:
    context_lines = []
    if camera_context:
        for key, value in camera_context.items():
            if not value:
                continue
            if key == "gemini_context_notes":
                continue
            context_lines.append(f"- {key}: {value}")
    context_block = "\n".join(context_lines) if context_lines else "- sem contexto adicional"

    prior_block = ""
    if prior_window_context:
        prior_block = f"\nPrior window context:\n{prior_window_context}\n"

    json_fields_extra = (
        "INCLUA NO JSON estes campos extras: fp_pattern_match (um de: real_dumping, "
        "traffic_passing, municipal_collection, pruning_crew, carroceiro_sorting, "
        "rain_blur, parking_dropoff, other) E audit_rationale (1-2 frases em pt-BR).\n"
        "REGRA V2: se fp_pattern_match esta em {traffic_passing, municipal_collection, "
        "pruning_crew, rain_blur, parking_dropoff}, entao infraction_confirmed DEVE ser false.\n"
        "Para os outros padroes (real_dumping, carroceiro_sorting, other), voce decide com "
        "base na evidencia visual de postura de deposito.\n"
    )

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
            "Analise a sequencia temporal de imagens como AUDITOR INDEPENDENTE do gate.\n"
            "Classifique a cena em um dos 8 padroes (fp_pattern_match) E decida sobre infracao.\n"
            f"{json_fields_extra}"
            f"Formato das imagens: {frame_desc}\n"
            f"{prior_block}"
            "Contexto da camera:\n"
            f"{context_block}"
        )

    frame_block = ", ".join(frame_names) if frame_names else "desconhecido"
    return (
        "Analise a sequencia temporal de imagens como AUDITOR INDEPENDENTE do gate.\n"
        "Classifique a cena em um dos 8 padroes (fp_pattern_match) E decida sobre infracao.\n"
        f"{json_fields_extra}"
        f"Nomes de frame permitidos: {frame_block}\n"
        f"{prior_block}"
        "Contexto da camera:\n"
        f"{context_block}"
    )


def apply_audit_v2_consistency(report: GeminiInfractionReportAudit,
                               request_id: Optional[str] = None) -> GeminiInfractionReportAudit:
    """V2 force-false: only when fp_pattern_match is in V2_FORCE_FALSE_PATTERNS
    (the 5 unambiguous FP categories). carroceiro_sorting / other / real_dumping
    are left to the model's own infraction_confirmed value.
    """
    pattern = report.fp_pattern_match or "other"
    if report.infraction_confirmed and pattern in V2_FORCE_FALSE_PATTERNS:
        logger.info(
            "audit_v2_consistency: fp_pattern_match=%s in force-false set "
            "-> forcing false (request_id=%s)",
            pattern, request_id,
        )
        report.infraction_confirmed = False
        report.confidence_0_100 = 0
    return report
