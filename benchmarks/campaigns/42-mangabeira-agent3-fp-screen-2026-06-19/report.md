# Camp 42 — Agent-3 FP-screener (Gemini 2.5 Flash vs Claude Haiku 4.5) — Mangabeira

**Data:** 2026-06-19 · **Câmera:** esp32_002 / cam_11 · **Tipo:** model-selection
**Custo do bench:** Gemini ~$0.10 + Haiku ~$3.0 (Bedrock) + visão/curadoria (Sonnet) ~$X

## Hipótese

Um **Agent-3** rodando depois do Agent-2, comparando a pilha **antes/depois**, consegue vetar
os FP de **revira/mexe (catador) + passante** sem matar descartes reais? Comparar **Gemini 2.5
Flash** vs **Claude Haiku 4.5 (Bedrock, prompt DR#1-tuned)** vs **baseline (sem screener)**.

## Dataset — `eval_manifest.csv` (243 eventos, persistido em `data/datasets/official/cam_mangabeira/`)

| gold | subtype | N | fonte |
|------|---------|---|-------|
| keep | real_deposit (CONFIRMADO) | 72 | comentário humano |
| kill | revira_explicit | 36 | comentário (catador/mexe/revira) |
| kill | revira_mexe | 25 | visão 2-votos |
| kill | passante_parado | 110 | 50 comentário + 60 visão |

Excluídos: 13 uncertain + 4 contested_deposit (REJEITADO pelo operador mas visão viu depósito).
Origem: corpus Camp 40 (`largeN/`, 260 eventos esp32_002 confirmados-pelo-Agent-2) + workflow de
visão (Sonnet, 2 votos, 89/102 concordância → +25 revira/catador, +60 passante).

## Método

Screener vê BEFORE + 2 mids + AFTER + **pile-crop hi-res** (bbox `[480,60,920,340]`, 2×, before+after).
Saída JSON `is_real_new_disposal` → **false = KILL (veta FP)**. Gemini: prompted JSON, thinking 0.
Haiku: DR#1-tuned (persona-forense + `<rules>` recall-guard >15%, frames XML, `output_config`
json_schema, thinking 1024). Scripts: `scripts/run_screener.py`, `scripts/screener_common.py`.

## Resultados (243 eventos, ponto de operação cru = KILL sempre que is_real=false)

| arm | TP-preserv | TP perdidos | FP-supp | revira_expl | revira_vis | passante | $/ev | p50 |
|-----|-----------:|-----------:|--------:|----------:|---------:|--------:|-----:|----:|
| baseline      | 100.0% | 0  | 0.0%  | 0%   | 0%   | 0%    | $0       | 0 |
| gemini_flash  | 51.4%  | 35 | 89.5% | 69.4%| 92.0%| 95.5% | $0.00039 | 3.4s |
| **haiku**     | 26.4%  | 53 | 95.3% | 86.1%| 96.0%| 98.2% | $0.01226 | 13.9s |

### Calibração por confiança (sweep — KILL se is_real=false E confidence ≥ T)

- **Gemini: confiança NÃO calibra** (bimodal). Tudo morre até T=90 (recall 51%); só em T=95
  recall sobe pra 67% (supp 66%) e T=100 zera. O modelo está ~90% **confiante nos erros**.
- **Haiku: confiança calibra**, mas o Pareto é fraco:

  | T | TP-preserv | FP-supp | revira-supp |
  |---|-----------:|--------:|------------:|
  | 0 (cru) | 26.4% | 95.3% | 90.2% |
  | 80 | 69.4% | 59.1% | 54.1% |
  | 85 | 80.6% | 49.1% | 41.0% |
  | **90** | **97.2%** | **8.2%** | **9.8%** |

  → no ponto recall-safe (≥95%), o Haiku só corta **~8% dos FP**.

### Ablação de frames (4 vs 8 globais) — Gemini

| frames | TP-preserv | FP-supp |
|--------|-----------:|--------:|
| 4 (base) | 51.4% | 89.5% |
| 8 | 47.2% | 86.5% |

**Mais frames NÃO recupera recall** (até piora) → o problema **não é amostragem**.

## Decisão: ❌ LLM Agent-3 screener NÃO é viável (enforce) sob o peso recall×3

- Ambos os modelos são exterminadores de FP agressivos mas **destroem o recall** (Gemini perde
  35/72 TP, Haiku 53/72). No ponto recall-safe, a supressão de FP colapsa pra ~8-10%.
- **Haiku domina o Gemini no Pareto** (mais supressão em todo nível de recall, melhor em
  revira_explicit 86% vs 69%, **e** a confiança calibra). Se um dia usar LLM-screener, é Haiku.
- Custo Haiku ~$0.012/ev (31× Gemini) + latência 14s (4×) — aceitável (Agent-3 só roda em eventos
  já confirmados, volume baixo), mas não compensa dado o trade-off de recall.

### Por que falha (causa-raiz, verificada visualmente)

A distinção revira-vs-depósito é **intrinsecamente sutil no Mangabeira**: a pilha é sempre grande
e crônica, e o depósito novo (sacola pequena, carrinho) **funde-se visualmente** na pilha. No TP
`d59d5309` (confirmado), o before (11:30) e o after (11:33) são quase idênticos a olho nu — o
carrinho de mão depositou material que não se distingue da pilha. Um screener estrito o bastante
pra pegar o catador também rejeita esses depósitos sutis. Reproduz **Camp 25** (pile_volume:
spec 74% mas recall 57%) e alinha com **Camp 41** (structural-delta = veto FP com perda de recovery aceita).

## Experimento de ensemble: LLM × structural-delta (Camp 41)

Calculei `census_ntiles_t32` (sinal vencedor do Camp 41) nos **mesmos 243 eventos/frames**
(`scripts/compute_structural.py`, mesma polígono/método) e combinei com o veredito do LLM
(`scripts/combine_signals.py`). Separação confirmada: census_ntiles_t32 mediana **TP=9 vs FP=1**.

**Melhor ponto de operação @ TP-preservação ≥ 95% (Haiku):**

| estratégia | FP-supp | revira-supp | TP-preserv | TP perdidos |
|------------|--------:|------------:|-----------:|------------:|
| structural sozinho (thr=1) | 42.1% | 11.5% | 95.8% | 3 |
| haiku sozinho (T=90) | 8.2% | 9.8% | 97.2% | 2 |
| interseção (Haiku ∩ struct) | 41.5% | 11.5% | 95.8% | 3 |
| **união (Haiku ∪ struct, T=90)** | **48.0%** | **19.7%** | 95.8% | 3 |

- **A interseção NÃO ajuda** (≈ structural sozinho — o structural é o fator limitante).
- A **UNIÃO** (KILL se *structural=sem-mudança* **OU** *Haiku=não-descarte com conf≥90*) é o melhor:
  **+6pp FP-supp e +8pp revira-supp vs structural sozinho, sem custo extra de recall** (3 TP perdidos
  nos dois). O Haiku@T=90 captura alguns revira que o structural perde, sem derrubar TP.
- Ganho modesto: o **structural-delta segue sendo o lever dominante**; o LLM é um add-on recall-safe
  pequeno (provavelmente não compensa o custo/latência do Haiku, mas fica documentado).

## Recomendações / próximos passos

1. **Não deployar LLM-screener em enforce.** Para reduzir FP de revira, o lever é o
   **structural-delta (Camp 41)** como veto shadow (já validado em holdout temporal).
2. **Ensemble testado:** interseção não ajuda; **união structural∪Haiku@90** dá +6pp FP recall-safe —
   só vale se o custo do Haiku ($0.012/ev) por +6pp for aceitável. Default = structural sozinho.
3. Se quiser supressão parcial advisory: **Haiku @ T=85** (recall 81%, corta ~49% dos FP) em
   **shadow**, nunca enforce.
4. Dataset persistido (`fp_subtype`) reutilizável para futuros testes de visão/CV no cam_11.

## Caveats

- "Confirmado/Rejeitado" são rótulos do operador (autoridade); 4 contested_deposit foram excluídos.
- Frames são uma amostra (12) da janela completa; a ablação 4→8 não mudou a conclusão.
- Haiku teve 34 throttling (Bedrock, workers=4) na 1ª passada; re-rodados com workers=2 → 243/243 ok.
