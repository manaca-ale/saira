# Camp 36 — Window-strategy latency simulator — REPORT

**Pergunta:** como reduzir a latência "descarte real → notificação na plataforma" (hoje
~1–7 min) sem regredir recall/FP, testando offline os levers #3 (sliding) e #4 (encolher
janela) + o lever POLL.

## TL;DR

1. **A latência hoje é dominada pela FASE DO POLL, não pela janela.** Mesmo evento/params,
   a latência varia **60–305s** só pela posição do descarte no ciclo de `POLL_INTERVAL=180s`.
   Os 2 eventos medidos ao vivo (193s, 59s) são duas amostras dessa distribuição.
2. **Dá pra cortar a latência ~pela metade (120s→~50–70s)** via POLL mais rápido e/ou sliding.
3. **MAS não é grátis — detectar mais cedo custa FP.** Medição limpa nos baselines:
   `poll60` ~**dobra** o FP (1.5→2.75/h); sliding aumenta menos.
4. **`slide_120_str60` é o melhor trade-off:** latência 70s (−42%) com o **menor aumento de FP
   (1.5→2.25/h)** e ainda **reduz FP no Mangabeira** (2.0→1.5/h).
5. **Encolher a janela fixa sozinho (#4) é cilada:** não corta latência e aumenta FP.
6. **Nota:** FP aqui é cascade-alone (sem BGSUB, que prod tem ligado e absorveria parte) →
   upper bound; a ordenação relativa entre estratégias é o que vale.

## Método (simulador validado)

Replay offline POLL-driven do cascade (gate flash-lite → detail flash, prompts/per-camera/
pile-crops idênticos a prod) sobre **21 timelines reais completas** do S3 (CONFIRMADO pelo
operador). Reimplementa `_process_with_gemini_cascade_window` sem mutar estado de prod;
chamadas Gemini memoizadas via Vertex.

**Portão de fidelidade (PASS):** com params de prod (240/48/12, poll180) o simulador
reproduz **exatamente** a janela confirmante e a latência dos 2 âncoras:
- a5a72209 (Arruda): F* 20:47:29, latência sim 195s vs medida **193s**
- c9c2c83e (Imbiribeira): F* 19:33:09, latência sim 55s vs medida **59s**

Descoberta-chave de fidelidade: o boundary da janela é **dirigido pelo poll** (o poll
processa todos os frames disponíveis como janela-trailing), não pela regra de 240s — por
isso o simulador modela o loop de poll explicitamente.

## Latência por estratégia (distribuição sobre fases de poll)

| estratégia | mode | janela | poll | **latência p50** | p90 | chamadas/det |
|---|---|---|---|---|---|---|
| `prod_240_poll180` (hoje) | fixed | 240s | 180s | **120s** | 255s | 2.4 |
| `prod_240_poll60` | fixed | 240s | 60s | **65s** | 155s | 3.0 |
| `prod_240_poll30` | fixed | 240s | 30s | 58s | 144s | 3.1 |
| `fix_90_poll60` | fixed | 90s | 60s | 64s | 150s | 3.3 |
| `fix_60_poll30` | fixed | 60s | 30s | 44s | 151s | 4.6 |
| `slide_120_str60` | sliding | 120s | 60s | 70s | 175s | 3.3 |
| `slide_90_str30` | sliding | 90s | 30s | 52s | 112s | 3.9 |

Latência estável nas 3 passadas da matriz (efeito grande, mecânico).

## ⚠️ Limitação: recall/FP do corpus positivo NÃO é confiável

O early-FP do baseline pulou de **0% (com pre-trim) para 22% (sem trim)** só mudando o
recorte. Causa: os timelines positivos são **clipes coalescidos de ~7 min** com atividade
pré-descarte; como o replay para na 1ª confirmação, o cascade às vezes dispara nessa
atividade (early-FP) e a separação TP/early-FP a ±30s não sobrevive à imprecisão do
`disposal_start` (rótulo CV, ±5–18 frames). **Conclusão metodológica: medir FP exige o
corpus de NEGATIVOS dedicado** (baselines sem_ocorrência) — ver seção abaixo.

## FP em baselines sem_ocorrência (medição limpa)

4 horas de baseline (Mangabeira + Imbiribeira, day+night, 2026-05-21). BGSUB não aplicado
(prod tem ON e absorveria parte) → FP cascade-alone, upper bound; ordenação relativa vale.

| estratégia | latência p50 | **FP/h overall** | FP Imbiribeira | FP Mangabeira |
|---|---|---|---|---|
| `prod_240_poll180` (hoje) | 120s | **1.5** | 1.0 | 2.0 |
| `prod_240_poll60` | 65s | 2.75 | 2.5 | 3.0 |
| `fix_60_poll30` | 44s | 2.75 | 2.5 | 3.0 |
| `slide_120_str60` | 70s | **2.25** | 3.0 | 1.5 |
| `slide_90_str30` | 52s | 3.5 | 4.0 | 3.0 |

**Fronteira de Pareto (latência↓ × FP↓):** `prod_240_poll180` (120s, 1.5) → `slide_120_str60`
(70s, 2.25) → `fix_60_poll30` (44s, 2.75). `poll60` e `slide_90` são **dominados**
(`fix_60_poll30` dá menos latência com FP igual/menor).

### FP COM BGSUB (pré-check offline fiel — Fase 2c)

⚠️ BGSUB é adaptativo/in-situ: nos baselines antigos (2026-05-21) o modelo atual marca a cena
inteira como foreground (persistence 29743 ≫ 1000 → não suprime nada). Verificado empiricamente
2026-06-05. **Só é fiel com frames RECENTES** que casam o modelo. Pré-check em ~1.3h de
no-disposal recente (esp32_001/002) com os `.npz` reais de prod:

| estratégia | latência p50 | Imbiribeira FP/h | Mangabeira FP/h |
|---|---|---|---|
| `prod_240_poll180` (hoje) | 120s | 0.68 | 2.36 |
| `prod_240_poll60` | 65s | 0.68 | 3.15 |
| **`slide_120_str60`** | 70s | **0.68** | **2.36** |

**Achado:** com o BGSUB real no loop, **`slide_120_str60` tem o MESMO FP do baseline** — o BGSUB
absorve a sobreposição das janelas sliding. Sliding corta latência ~½ com **custo de FP ≈ zero**.
`poll60` ainda piora o Mangabeira (2.36→3.15). ⚠️ Amostra pequena (~1.3h, raw FP 1–6) → indicativo;
o **shadow ao vivo** dá o número definitivo. (Bug latente visto: `evidence_summary > 600 chars`
falha a validação do `GeminiInfractionReport` em ~1 call — pré-existente, não introduzido aqui.)

## Recomendação

A latência hoje (~120s p50, até 300s+) é o gargalo do flagrante. Reduzir custa FP — escolha
o ponto da fronteira de Pareto conforme o apetite por FP:

- **Melhor trade-off → `slide_120_str60`** (precisa de código: sliding overlapping no worker).
  Latência 70s (−42%) com o menor aumento de FP (1.5→2.25/h) e **reduz FP no Mangabeira**.
  Recomendado se for mexer no código.
- **Interino zero-código → `POLL_INTERVAL=60`** (1 env var, reversível). Latência 65s mas FP
  ~dobra (1.5→2.75/h). Aceitável como ponte até o sliding, **especialmente porque o BGSUB de
  prod (não modelado aqui) deve absorver parte desse FP** — validar ao vivo a taxa
  operador-facing antes de manter.
- **Latência agressiva → `fix_60_poll30`** (44s) só se o FP 2.75/h for tolerável.
- **Não fazer:** encolher só a janela fixa com poll lento (#4 puro) — não corta latência.

**Próximo passo sugerido:** se for pro sliding, implementar no worker como flag
(`GEMINI_SLIDING_WINDOW_ENABLED`) + shadow A/B numa câmera, medindo FP operador-facing real
(com BGSUB). Recall limpo exige re-rotular `disposal_start` manualmente (o corpus coalescido
não permite medir recall de forma confiável — ver limitação acima).

## Artefatos
- `sim.py` — simulador reutilizável (fixed/sliding, memoizado, Vertex)
- `run_fidelity.py` / `run_matrix.py` / `run_negatives.py`
- `corpus/positives/` (21 eventos) — timelines + meta + contact sheets
- `results_agg.json`, `results_raw.json`, `results_negatives*.json`
- caches Gemini em `cache/` (re-run = cache hit)
