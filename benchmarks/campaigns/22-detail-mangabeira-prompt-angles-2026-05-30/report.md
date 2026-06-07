# Campanha 22 — MANGABEIRA prompt angles (Flash 2.5) 2026-05-30

> ✅ **CONCLUÍDA** — vencedor parcial: **MANGABEIRA_E (negative-first)** é o melhor candidato a deploy,
> mas perde 2 TPs reais vs V1 baseline. Trade-off recall vs specificity é o gargalo.

## Hipótese

Camp 21 mostrou que `DETAIL_PROMPT_V3_MANGABEIRA` com Flash atinge 75% recall e
33% specificity em cam_11. Análise dos 14 erros (4 FN_NEW + 7 FP_PERSIST + 3 FP_NEW
vs V1 baseline) apontou para **2 modos de falha distintos**:

1. **Confabulação**: Flash inventa "depositar" quando há só postura ambígua
2. **Anti-padrões inconsistentes**: o modelo aplica APs em ~60% dos casos onde deveria

Testamos 2 ângulos mecânicos distintos atacando estes modos:

- **C (Two-step checklist)**: força evidência S/N obrigatória por pessoa relevante
- **E (Negative-first)**: inverte default (assume CON) e força aplicação explícita de APs

## Dataset (production-parity)

Snapshot do DB de prod em 2026-05-30 ~10:00 BRT. **n=40 events cam_11** (operador
adicionou 5 labels novos entre camp 21 manhã e camp 22 manhã).

| Cohort | n | Comparação válida? |
|---|---|---|
| Single-call | 29 | ✅ prod parity |
| Coalesced | 5 | ⚠️ bench underestima |
| Sem audit | 6 | ⚠️ eventos pré-audit log |

**Production parity:**

| Parâmetro | Prod | Bench | Status |
|---|---|---|---|
| `GEMINI_CASCADE_MAX_FRAMES` | 48 | 48 | ✅ |
| `GEMINI_MOSAIC_AGENT2` | off | off | ✅ |
| Modelo | gemini-2.5-flash | gemini-2.5-flash | ✅ |

Cache de frames reusado de `/tmp/flash_per_camera/frames/esp32_002/` (camp 21).
Provider: **Vertex AI** (location=global, SA `saira-bench-vertex@gen-lang-client-0841492152`).

## Resultados — single-call cohort (n=29)

| Arm | Acc | TP | TN | FP | FN | Recall | Spec | $/event |
|---|---|---|---|---|---|---|---|---|
| **Flash V1 baseline** (prod) | 53,8% | 11 | 3 | 11 | 1 | **91,7%** | 21,4% | $0,01 |
| Flash + MANGABEIRA orig (camp 21) | 51,9% | 9 | 5 | 10 | 3 | 75,0% | 33,3% | $0,01 |
| Flash + MANGABEIRA_C checklist | 44,8% ❌ | 10 | 3 | 14 | 2 | 83,3% | 17,6% | $0,013 |
| **Flash + MANGABEIRA_E neg-first** | **62,1%** ✅ | 9 | 9 | 8 | 3 | 75,0% | **52,9%** | $0,011 |

### Insights

- **E vence em acc e specificity** — supera todos os arms na cohort clean
- **C regride acc e specificity** — checklist força preenchimento mecânico de 5/5, e o
  modelo confabula 5/5 com facilidade em casos ambíguos (problema migra do prompt
  livre pro checklist)
- **V1 baseline imbatível em recall (91,7%, 1 FN)** — qualquer prompt mais restritivo
  perde TPs
- **Custo flat (~$0,011)** — diferença entre arms é ruído de tokens

## Resultados — full cohort (n=35-39)

| Arm | n | Acc | Recall | Spec |
|---|---|---|---|---|
| Flash V1 baseline | 35 | 60,0% | 85,0% | 26,7% |
| MANGABEIRA orig | 37 | 56,8% | 71,4% | 37,5% |
| MANGABEIRA_C | 39 | 51,3% | 81,0% | 16,7% |
| **MANGABEIRA_E** | 39 | **61,5%** | 66,7% | **55,6%** |

## Cross-bucket vs V1 (single-call)

### MANGABEIRA_E (vencedor)

| Bucket | Count | Significado |
|---|---|---|
| ✅ FP_FIXED | 5 | Filtrou corretamente FPs do V1 (AP2/AP3 acionados em passantes) |
| ✅ TP_NEW | 0 | Não recuperou nenhum TP que V1 perdeu |
| ❌ FN_NEW | 2 | Rejeitou TPs reais que V1 acertou |
| ❌ FP_NEW | 1 | Introduziu 1 FP novo (5520e0c7: agachado 2:30, AP4 não acionado) |
| ⚪ FP_PERSIST | 6 | Continua confirmando casos ambíguos (default CON quando nenhum AP aplica) |
| ⚪ FN_BOTH | 1 | be6b5e67 (caso difícil — guarda-chuva noturno) |

**Net change vs V1**: −5 FPs filtrados, −2 TPs perdidos, +1 FP novo, líquido = qualidade sobe.

### MANGABEIRA_C (regressão)

| Bucket | Count | Significado |
|---|---|---|
| ✅ FP_FIXED | 3 | |
| ❌ FP_NEW | 3 | Checklist preenchido 5/5 em cenas ambíguas |
| ⚪ FP_PERSIST | 8 | Modelo "vê" Q4 e Q5 mesmo sem evidência clara |

**Conclusão C**: o checklist obrigatório não reduz confabulação — só formaliza a
narrativa confabulada. Modelo escreve "Q4=SIM (saiu sem o saco)" mesmo quando não
viu a transição. Descartar.

## Análise qualitativa dos erros do E

### FN_NEW (TPs que E perdeu, V1 acertou)

**d59d5309 (CON real)**: "AP3 APLICA — pessoa com caixa azul passa sem depositar".
Modelo achou que a pessoa relevante apenas atravessou. **AP3 está sobre-aplicado
quando há múltiplos pedestres na cena**.

**3c840ac4 (CON real, carrinho de mão com entulho)**: "AP2 APLICA — todas em movimento,
sem paradas prolongadas". Modelo subestimou a parada curta. **AP2 (passantes) precisa
exigir "TODAS as pessoas em movimento DURANTE TODA a sequência" — não basta uma
janela predominantemente em trânsito**.

### FP_NEW (E introduziu 1 FP que V1 acertou)

**5520e0c7 (REJ, agachado 2:30 manipulando)**: "AP1-7 NAO_APLICA. Decisao: CON".
Modelo não classificou agachamento prolongado como AP4 (catador) porque "fluxo
material da pilha pra pessoa" não foi visualmente claro. **AP4 precisa de gatilho
adicional: "permanência agachada >30s sem objeto novo no chão = APLICA, default REJ"**.

### FP_PERSIST (E não filtrou 6 FPs do V1)

Padrão: cenas com pessoa que **chega com sacola, para por ~5s, sai sem sacola visível**.
Modelo não encontra AP claro porque a cena visualmente **parece** descarte real, e o
default invertido escolhe CON. Esses casos provavelmente são vasculhamento rápido ou
descarga seletiva (catador), mas o operador rejeitou.

**Conclusão**: para filtrar essa classe de FP, prompting sozinho não basta — precisa
de tracking temporal explícito (ByteTrack + RTMPose) ou DINOv2 multimodal.

## Recomendação cirúrgica

| Decisão | Status |
|---|---|
| ❌ **Não deployar MANGABEIRA_C** | Regrediu specificity vs MANGABEIRA orig |
| ⏸ **MANGABEIRA_E candidato a shadow A/B** | Vence em acc/spec mas perde 2 TPs vs V1 |
| 🎯 **Próxima iteração — refinar APs do E** | AP2/AP3 sobre-aplicados (FN_NEW); AP4 sub-aplicado (FP_NEW) |
| 🧪 **Pipeline 2 estágios?** | V1 (alto recall) → E como pós-filtro de especificidade |

### Trade-off operacional (cam_11 ~17 detections/dia)

| Métrica | V1 prod (atual) | MANGABEIRA_E | Δ |
|---|---|---|---|
| Operador vê | 22/dia (11 TP + 11 FP) | 17/dia (9 TP + 8 FP) | **−22% workload** |
| Ocorrências perdidas | ~1/dia | ~3/dia | +2/dia (+60/mês) ❌ |
| Custo | $0,17/dia | $0,19/dia | +$0,02/dia (+$0,60/mês) |

⚠️ **O trade-off é exatamente o mesmo que apareceu na camp 21 com Pro per-cam**.
Decisão final depende de prioridade real do operador: filtrar mais FP ou pegar mais
ocorrências reais?

## Caveats

1. **n=29 single-call é pequeno** — σ de fold ±10pp pelo menos. Repetir com n>50 quando
   crescer (operador labelou +20 events em 2 dias).
2. **Coalesced events (n=5)** têm input incomparável (prod = 2+ calls, bench = 1).
   Em prod, E pode recuperar parte dos coalesced TPs via 2ª call independente.
3. **C falhou no mecanismo principal** — checklist obrigatório não desfaz confabulação;
   só formaliza. **Não confundir estrutura ≠ veracidade do raciocínio**.
4. **E depende do default invertido** — quando nenhum AP aplica, decide CON. Isso é
   por design (operador filtra), mas significa que recall não pode subir só com
   prompting; só descendo specificity.

## Decisão

✅ **MANGABEIRA_E como melhor prompt single-shot** — mas decisão de deploy depende:

1. **Refinar APs antes de deploy** — AP2/AP3 (passantes) e AP4 (catador) precisam de
   gatilhos mais discriminativos pra recuperar os 2 FN_NEW e o 1 FP_NEW
2. **Validar shadow A/B em `test-saira`** por 1-2 semanas com ambos os veredictos
   (V1 + E) em colunas paralelas
3. **Considerar 2-stage pipeline** — V1 (alto recall) → E como pós-filtro de specificity
4. **Esperar Deep Research VLM pipeline** (em background) — pode sugerir arquiteturas
   alternativas (ensemble, debate, multi-prompt voting) que mudem a estratégia

❌ **Descartar MANGABEIRA_C** — checklist obrigatório não atacou o mecanismo de
confabulação; só formalizou o raciocínio confabulado.

## Reprodução

Scripts em `scripts/`:

- `flash_mangabeira_angles.py` — roda 1 arm (env `ANGLE=C` ou `ANGLE=E`)
- `compare_camp22.py` — comparativo cross-arm com single-call cohort filter

Prompts source em `prompts/`. Resultados completos em `results/`. Caches reusam
`/tmp/flash_per_camera/frames/esp32_002/` (camp 21).

## Custo total

| Arm | Custo |
|---|---|
| C | $0,51 |
| E | $0,41 |
| **Total camp 22** | **$0,92** |

## Memórias relacionadas

- [[project_camp21_per_camera_detail_2026-05-30]] — origem (Pro per-camera win em cam_11)
- [[feedback_bench_match_prod_exactly]] — N=48, coalesced caveat
- [[reference_vertex_ai_bench_setup]] — Vertex flags (sem 503)
- [[project_dinov2_filter_2026-05-29]] — DINOv2 cam_11 não-separável (47% acc) explica
  porque prompting não basta pra FP_PERSIST do tipo "agachou 5s ambíguo"
