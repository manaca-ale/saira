# Campaign 47 — pi-cam-001 model migration (current vs Gemini-3)

**Data:** 2026-07-22 · **Tipo:** seleção de modelo · **Câmera:** pi-cam-001 (event-driven)

## Hipótese

Os modelos de produção `gemini-2.5-flash-lite` (gate) + `gemini-2.5-flash` (detail) serão
desligados em **16/out/2026**. Os substitutos recomendados pelo Google (gate
`gemini-3.1-flash-lite`, detail `gemini-3.6-flash`) mantêm recall/FP com custo aceitável na
pi-cam-001, permitindo migração drop-in?

## Configuração

| item | valor |
|---|---|
| Gate | Agent-1, `analyze_new_litter_with_gemini`, thinking_budget=1024, trigger ≥85 |
| Detail | Agent-2, `analyze_with_gemini`, prompt V1 (`GEMINI_PROMPT_VERSION=current`) |
| Janela | event-driven: `subsample_frames(48)` → `fit_frames_to_payload(8MB)` (= prod) |
| Dataset | `cam_picam001` — 30 tp · 37 fp · 15 indefinido · 40 baseline (122 eventos) |
| GT | por detecção (prod cria 1 detecção por grupo de eventos) + por evento |
| Auth | AI Studio key (conta Saira - Testes); `GEMINI_USE_VERTEX=false` |
| Custo total | ~US$ 2,0 (current 0,12 · repl 1,45 · cheap 0,39) |

## Resultados

### Por DETECÇÃO (métrica primária — dispara se qualquer evento da detecção dispara)

| braço | gate / detail | TP-recall | FP-rate¹ | baseline-fire² | custo/evt | lat p50 |
|---|---|---|---|---|---|---|
| **current** | 2.5-flash-lite / 2.5-flash | **87,5%** (14/16) | 40,7% (11/27) | 0% (0/40) | $0,00099 | 10,9s |
| **repl** | 3.1-flash-lite / 3.6-flash | 62,5% (10/16) | 21,4% (6/28) | 2,5% (1/40) | $0,0119 | 4,9s |
| **cheap** | 3.1-flash-lite / 3.5-flash-lite | 31,2% (5/16) | 14,3% (4/28) | 0% (0/40) | $0,0032 | 4,7s |

### Por EVENTO (secundária)

| braço | TP-recall | FP-rate | baseline-fire |
|---|---|---|---|
| current | 80,0% (24/30) | 40,0% (14/35) | 0% (0/40) |
| repl | 46,7% (14/30) | 18,9% (7/37) | 2,5% (1/40) |
| cheap | 23,3% (7/30) | 10,8% (4/37) | 0% (0/40) |

¹ **FP-rate é enviesado**: o set `fp` são, por construção, eventos que o pipeline ATUAL
já disparou (gate+detail) e o operador rejeitou. Logo mede "quanto o braço re-dispara nos
FPs do modelo atual", não especificidade pura. Os modelos-3 disparam menos em tudo (ver
abaixo), então caem aqui junto com o recall.
² **baseline** (movimento sem descarte = negativos verdadeiros não vistos por nenhum
modelo) é o sinal limpo de especificidade: **todos os braços ~0%** → nenhum dispara em
negativo fácil.

## Decisão: NÃO migrar drop-in

**Os substitutos recomendados REGRIDEM o recall com o prompt V1 atual.** `repl` derruba o
recall por detecção de **87,5% → 62,5% (−25pp)** e custa **12× mais** ($0,0119 vs $0,00099).
`cheap` colapsa para 31,2%. É o pior dos mundos: menos recall E mais caro.

**Leitura:** o prompt V1 foi calibrado para o comportamento do Gemini-2.5. Os modelos
Gemini-3 são **mais conservadores** com o mesmo prompt — disparam menos (cai FP e baseline,
mas mata recall real). A migração NÃO é drop-in; exige **recalibrar o prompt para Gemini-3**.

Ponto positivo: há **runway até 16/out**. Especificidade (baseline) está sã em todos.

## Próximos passos

1. **Campanha de re-tuning do prompt para Gemini-3** (antes de migrar): ajustar V1 →
   "V1-g3" para recuperar recall no `gemini-3.1-flash-lite`/`gemini-3.6-flash`, re-rodar
   este mesmo dataset. Alvo: recall por detecção ≥ 85% mantendo baseline ~0%.
2. **Ablação gate vs detail**: braço `gate=2.5-flash-lite + detail=3.6-flash` para isolar
   se a perda de recall vem do gate-3.1 ou do detail-3.6 (hoje `repl` troca os dois juntos).
3. Reavaliar `gemini-3.6-flash` (10× custo) vs `gemini-3.5-flash-lite` no detail só depois
   de o recall voltar — se o flash-lite-3.5 recuperar recall com prompt novo, é a opção barata.

## Fase 2 — prompt reescrito p/ Gemini-3 + consolidação (pergunta: dá pra eliminar o detail?)

Motivada pela pesquisa `pesquisas/saira_vlm_vision_performance.md` (Gemini-3 sob schema
estrito SEM raciocínio = "Anomalia C3" → sub-dispara; recomenda 1 chamada 3.1-flash-lite
com thinking). Prompts gate+detail reescritos (raciocínio-primeiro, inclui descarte A PÉ,
prior de hotspot, ambiguidade→descarte) + `thinking_level=high`. Braços em `results/bench_picam_g3.csv`:

| braço | pipeline | recall/det | FP-rate | baseline-fire | $/evento | vs atual |
|---|---|---|---|---|---|---|
| current | 2.5-lite gate + 2.5-flash detail (V1) | **93,8%** (15/16) | 42,9% | 0% | $0,00101 | 1× |
| g3_v1 | 3.1-lite + 3.5-flash (V1 + think) | 68,8% | **14,3%** | 2,5% | $0,00486 | 4,8× |
| g3_new | 3.1-lite + 3.5-flash (prompt novo + think) | 75,0% | 35,7% | 7,5% | $0,00835 | 8,3× |
| g3_unified | **só 3.1-lite** 2 estágios (prompt novo) | 75,0% | 44,4% | 10% | $0,00276 | 2,7× |
| **unified_single** | **1 chamada 3.1-lite** janela cheia | **100%** (16/16) | 76,9% | 27,5% | $0,00338 | 3,3× |

**Diagnóstico:** o 3.1-lite em 2 estágios (g3_unified) perde 3 TPs — 1 ambíguo (van) e
**2 descartes claros perdidos no GATE** (janela 32–85 frames, gate vê só 5 amostrados → o
ato de depositar cai entre amostras). A **chamada única** (vê a janela CHEIA) recupera
TODOS (100% recall) — prova que o modelo é capaz — mas **superdispara** (FP 77%, baseline
27,5%): o gate esparso agia como filtro de FP. Sweep de confiança na chamada única (grátis,
dado guardado): conf≥100 → 81% recall / 42% FP / 2% baseline ≈ ponto do current. A confiança
é MAL calibrada (superconfiante em FP — padrão "C3"), então limiar sozinho não separa.

**Resposta "dá pra eliminar o detail e ficar só com o 3.1-lite?":**
- **Custo: SIM, não é o gargalo.** 1 chamada 3.1-lite = ~$0,0034/evento (3,3× o atual, mas
  ambos ~centavos/1000 eventos). O susto de 5–9× era só por escolher detail CARO (3.5/3.6-flash).
  Ficando no tier flash-LITE (3.1), custo continua na mesma ordem de grandeza de hoje.
- **Qualidade: EMPATE, não ganho.** Melhor caso ≈ qualidade atual com pipeline mais simples
  (1 chamada, −latência, −código). Para SUPERAR o current (recall↑ E FP↓) falta: (a) pré-filtro
  CV/BGSUB/structural barato p/ conter a enxurrada de FP (já existe nas esp32), e/ou (b) prompt
  da chamada única afinado p/ especificidade + confiança calibrada.

**Recomendação de migração (deadline 16/out):** migrar para **1 chamada `gemini-3.1-flash-lite`
na janela cheia** (sai dos modelos 2.5 depreciados, 1 chamada, ~$0,003/evento) com prompt
re-afinado p/ especificidade + limiar de confirmação alto, APOIADA por um pré-filtro
CV/structural p/ derrubar FP. Não migrar para detail 3.5/3.6-flash (5–9× custo, sem ganho).
Follow-up: campanha de calibração do prompt single-call (subir especificidade sem perder o
recall de 100%) — o modelo já prova que enxerga tudo; o problema é seletividade.

## Fase 3 — media_resolution=low, custo real e o dial recall↔especificidade

Resultados em `results/bench_picam_g3low.csv` (custo já com thinking real + tokens de imagem):

| braço | recall/det | FP¹ | baseline² | $/ev | tok_in/ev |
|---|---|---|---|---|---|
| current (2.5, prod) | 93% (15/16) | 42% | **0%** | ~$0,002³ | — |
| unified_low (1 chamada, LOW) | 100% | 69% | 23% | $0,00226 | 7.368 |
| unified_low_8f (1 chamada, LOW, 8 frames) | 100% | 74% | 23% | $0,00179 | 3.302 |
| **unified_low_2s** (2-estágios, LOW, recall-first) | **93%** (15/16) | 57% | 15% | $0,00245 | 7.091 |
| unified_low_2s_spec (2-estágios, LOW, ESPEC-first) | 68% | 32% | 10% | $0,00208 | 5.182 |
| unified_low_spec (1 chamada, LOW, ESPEC-first) | 81% | 50% | 12% | $0,00212 | 7.038 |

¹ FP-set enviesado (são FPs do 2.5). ² baseline = negativos verdadeiros. ³ subestimado (sem thinking).

**Achados:**
1. **`media_resolution=low` corta o input de imagem ~4×** (~1.101→265 tok/img) SEM perder recall
   (100%). Custo real da chamada única cai p/ **$0,0023** ≈ custo do current. **Custo deixou de ser o gargalo.**
2. **Custo é ~linear no nº de imagens**: full (23f)→8f: input 7.368→3.302, custo $0,0023→$0,0018, recall
   ainda 100%. Dois levers de custo: nº de frames × media_resolution.
3. **Correção de custo importante**: minha 1ª conta OMITIA os thinking tokens (cobrados como output);
   o 2.5-flash pensa ~3k tok/ev, então TODOS os braços high-res estavam subestimados ~2×. Runner
   corrigido (`cost()` soma thinking + colunas tok_in/out/think). Os braços LOW já têm custo correto.
4. **Fidelidade auditada** (`scripts/fidelity_check.py`): o `agent1_confidence` real da prod (95) BATE
   com o gate do benchmark (95) em **15/16 TPs** → o benchmark replica a produção. A diferença 2.5 vs
   3.1 é comportamento de modelo: 2.5 gatilho-leve (recall alto/FP alto); 3.1 cético (precisa de mais
   frames no gate; na janela cheia pega 100%).
5. **O dial recall↔especificidade não fecha só com prompt**: recall-first = 100%/23%-baseline;
   espec-first = 68-81%/10-12%-baseline. Inspeção visual dos baseline-fires do 3.1 = FP genuínos
   (catador com carroça reviran­do; ciclista passando) — os padrões conhecidamente difíceis.
   Caveat metodológico: a baseline SÃO os eventos que o 2.5 rejeitou em prod → o 0% do 2.5 é
   parcialmente circular.

**Recomendação FINAL de migração:** **3.1-lite low-res, 2-estágios, prompt recall-first (g3), thinking=high**
(`unified_low_2s`: 93% recall ≈ current, ~$0,0025/ev ≈ custo de hoje) **+ pré-filtro structural-delta**
p/ a especificidade (mata "pilha inalterada + pessoa presente" de graça na CPU). Não espremer
especificidade só no LLM (consistente com o histórico: veto de sinal único fura recall). Próximo:
**shadow A/B em prod só na pi-cam-001** logando custo/tokens/decisão de TODO evento p/ comparar 2.5 vs 3.1
por 1-2 semanas.

## Caveats

- **N pequeno**: 16 detecções TP (câmera no ar desde 14/07). Direção é clara mas os
  intervalos são largos — reconfirmar com mais dados nas próximas semanas.
- **`repl` confunde gate+detail** (troca os dois) — ver ablação no passo 2.
- **4 erros de schema** (validação JSON) no braço `current` (detail 2.5-flash), 4/122 —
  truncamento ocasional do JSON verboso; não afeta as conclusões.
- **Fidelidade do gate**: `first_frame=win[0]` (estado de janela anterior de prod não é
  reproduzível do DB); `prior_window_context=None` → threshold=85. Afeta só o gate,
  marginalmente. Checagem: 5/5 TP por detecção reproduzem prod nos modelos atuais.
- **Custo do detail-3.6**: confirma o ~10× do sticker ($1,50/$7,00 vs $0,15/$0,60 por 1M tok).
