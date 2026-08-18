# Campanha 52 — O prompt V3 do gate ainda paga o próprio custo?

**Data:** 2026-08-04 · **Modelo:** `gemini-2.5-flash-lite` (Vertex, projeto `saira-tests-260520`)
**Custo da campanha:** US$ 1,76 (1.380 chamadas)

## Pergunta

A investigação do pagamento de 01/08 achou uma assimetria: esp32_001 e esp32_002 carregam
um system prompt de ~3.571 tokens (V3 + addon por câmera) contra 358 tokens (V1) nas outras
quatro câmeras — **~3.200 tokens extras em toda chamada de gate, ~R$ 46/mês**. As imagens são
idênticas em dimensão nas seis (1280×720), então o delta é prompt puro.

O V3+B3 entrou na esp32_002 em 28/05 e o E_modality na esp32_001 pela campanha 31. Três meses
depois, com amostragem de frames alterada (`027b33c51`), **os tokens extras ainda compram o
recall que compravam em maio?**

## Resultado — o V3+addon se paga, com folga

Recall e especificidade excluindo erros (os 16 erros caíram **todos** em eventos FP, nenhum em
TP/missed — o recall não tem viés de erro):

### cam_mangabeira (esp32_002) — 80 positivos (74 TP + 6 missed), 214 FP

| Braço | Recall | Especificidade | Tokens in | Custo |
|---|---|---|---|---|
| **A_prod** (V3+B3) | **48/80 = 60,0%** | 41,5% | 5.646 | $0,414 |
| B_v3_base (V3 sem addon) | 29/80 = 36,2% | 69,0% | 5.138 | $0,418 |
| C_v1 (prompt curto) | 12/80 = 15,0% | 77,7% | 2.358 | $0,290 |

### cam_imbiribeira (esp32_001) — 20 TP, 147 FP

| Braço | Recall | Especificidade | Tokens in | Custo |
|---|---|---|---|---|
| **A_prod** (V3+E_modality) | **13/20 = 65,0%** | 56,2% | 5.588 | $0,240 |
| B_v3_base (V3 sem addon) | 8/20 = 40,0% | 84,1% | 5.141 | $0,236 |
| C_v1 (prompt curto) | 9/20 = 45,0% | 76,6% | 2.361 | $0,164 |

## Decisão: MANTER o V3 + addon nas duas câmeras

Pelo critério combinado (recall manda, custo só desempata — é câmera de fiscalização), o
`A_prod` vence em recall nas duas, sem ambiguidade. **A alavanca de R$ 46/mês está morta,
e morta com número.**

Cair para V1 na Mangabeira custaria **45 pontos de recall** (60% → 15%): 36 dos 80 descartes
confirmados deixariam de ser vistos. Não existe economia que justifique isso.

## O que mais apareceu

**1. O addon de 540 tokens é o componente mais valioso do prompt inteiro.**
Na Mangabeira, o B3 sozinho vale **+24pp de recall** (36,2% → 60,0%) por 540 tokens — cerca de
R$ 7/mês. É a melhor relação recall/token de todo o pipeline. O achado do dual-gate da
campanha 19 continua de pé três meses depois.

**2. V3 sem addon é uma configuração RUIM — pior que V1 na Imbiribeira** (40,0% vs 45,0%).
Ou seja, a base V3 não carrega o resultado sozinha: quem faz o V3 funcionar nessas cenas é o
addon por câmera. Se alguém um dia pensar em "simplificar removendo os addons", este é o
número que diz não.

**3. O trade recall↔especificidade é explícito e intencional.** O `A_prod` tem a PIOR
especificidade dos três braços nas duas câmeras (41,5% e 56,2%). O prompt caro está comprando
recall com FP — que é exatamente o desenho, já que o detail existe para filtrar depois
(rejeita 63% do que o gate passa).

**4. O recall absoluto da Mangabeira é baixo — 60% no melhor braço.** Isso não é resultado
desta campanha (é a linha de base de prod), mas merece atenção porque em 02/08 o BGSUB entrou
em **enforce** nessa mesma câmera. Os dois efeitos se acumulam. Como foram medidos em
populações diferentes (dataset oficial vs detecções vivas), não dá para multiplicar os
números — mas a revisão de ~16/08 do BGSUB deveria olhar o quadro de recall da Mangabeira
como um todo, não só o delta do BGSUB.

## Fidelidade

O runner reproduz os tokens de produção nas **duas** configurações — não só na atual:

| Config | Bench | Prod (`gemini_call_log`, julho) | Δ |
|---|---|---|---|
| A_prod cam_mangabeira | 5.646 | 5.605 (esp32_002) | +0,7% |
| A_prod cam_imbiribeira | 5.588 | 5.602 (esp32_001) | −0,3% |
| C_v1 | 2.358–2.361 | 2.374–2.431 (esp32_003/005) | dentro da faixa |

Paridade conferida contra o `saira-yolo-worker-prod` em 04/08: `gemini-2.5-flash-lite`,
thinking 2048, trigger ≥85, 5 frames individuais (first + 3 mids **uniformes** + last),
**sem mosaico**, `camera_context` com os valores reais do banco de produção.

⚠️ Dois desvios de paridade da campanha 44 foram corrigidos aqui e valem para campanhas
futuras: (a) o `_mid()` da 44 usa 25/50/75%, mas prod mudou para espaçamento **uniforme** no
commit `027b33c51`; (b) prod passa `horario_local` no `camera_context`, que a 44 omitia.

Os três braços foram provados diferentes **antes** de gastar chamada, interceptando na borda
da rede: system prompt 14.286 / 12.124 / 1.430 chars e schema `GeminiNewLitterReportV3` nos
braços A e B contra `GeminiNewLitterReport` no C.

⚠️ **Desvio conhecido e declarado (braço C_v1):** o despacho de versão é hardcoded em
`detector_gemini.py:1156` e lê `device_id` do `camera_context`, então o braço V1 é alcançado
**omitindo essa chave**. Como `_new_litter_user_prompt` despeja todas as chaves no texto, o
braço C perde a linha `- device_id: esp32_00X` (~5 tokens). Foi a escolha deliberada: a
alternativa (monkeypatch dos símbolos V3) deixaria `apply_v3_gates` rodando sobre um report
V1 — configuração que não existe em nenhum ambiente. A lógica de pós-processamento V1 vive
inline no `else:` e não é importável, então reimplementá-la seria a infidelidade que
invalidou as campanhas 20/21. Omitir `device_id` preserva o caminho V1 inteiro: prompt,
schema e pós-gates.

## Erros

16 de 1.380 chamadas (1,2%): 429 `RESOURCE_EXHAUSTED` e timeouts, com fallback de região
`global → us-central1` acionado. **Todos em eventos FP**, nenhum em TP/missed. Os números
acima excluem os erros; o `results.json` guarda as linhas cruas.

## Reprodução

```
python benchmarks/campaigns/52-gate-prompt-v1-vs-v3-cost-2026-08-04/scripts/bench_gate_prompt_cost.py
```
Requer ADC válido (`gcloud auth application-default login`) e `services/.env.benchmark`.
`--smoke` roda 6 eventos por braço primeiro.
