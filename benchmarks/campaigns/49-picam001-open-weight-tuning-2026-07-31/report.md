# Campanha 49 — consertar os três open-weight (2026-07-30/31)

## Hipótese

O Camp 48 concluiu "não migrar", mas com **três falhas de desenho**: mesmo modelo nos
dois estágios, limiar de gate fixo em 85 para todos, e prompt cego para o modo de falha
desta câmera (23 dos 37 FPs eram *"há lixo, mas não vi o momento"*; 21 citavam
catadores). Quanto do gap era o modelo e quanto era o harness?

## Configuração

| Item | Valor |
|------|-------|
| Dataset | `cam_picam001` **corrigido na Fase 0** — 35 tp (19 det) · 32 fp (25 det) · 40 baseline · 15 ind |
| Prompt novo | `scripts/_prompts_v4picam.py` — critério de **flagrante** + **cláusula de catador** |
| Gate | paramétrico: `gate_img` (orig/low) × `gate_mids` (3 ou 13 → 5 ou 15 frames) |
| Cascata | heterogênea habilitada (`<gate>+<detail>:<perfil>`) |
| Controle V1 | **importado** do Camp 48 (122 linhas), reavaliado contra os rótulos novos |
| Controle V4 | `current_v4` rodado de verdade — define a barra de precisão |
| Chamadas | 1.098 (Bedrock) + 122 (Gemini) + 122 importadas |

---

## Fase 0 — a revisão humana mudou o dataset

9 eventos ambíguos revisados pelo operador: **6 catador · 3 descarte**. Os 3 descarte
estavam rotulados `fp`. Reclassificação aplicada **por detecção** (a unidade semântica do
dataset), arrastando 2 eventos-irmão: **5 eventos de `fp` para `tp`**.
`cam_picam001`: tp 30→35, fp 37→32. Valores antigos preservados em campos `relabel_*`.

**Isso subiu a barra do controle**, porque parte do que o Camp 48 contou como erro de
produção era erro de rótulo:

| | recall/det | precisão | FP/det |
|---|---|---|---|
| controle, rótulos antigos | 87,5% (14/16) | 51,9% | 46,4% |
| controle, rótulos corrigidos | **89,5% (17/19)** | **63,0%** | **40,0%** |

Os 6 catador confirmam os rótulos existentes — e confirmam o diagnóstico: **catador é o
eixo único de erro desta câmera**, tanto no conjunto FP quanto no baseline.

---

## Resultado 1 — o prompt V4 melhora a PRODUÇÃO ATUAL

| braço | recall/det | precisão | FP/det | baseline | $/ev |
|---|---|---|---|---|---|
| `current_v1` (prompt de prod) | 17/19 · 89,5% | 63,0% | 10/25 · 40% | 0/40 | 0,00725 |
| **`current_v4`** | **18/19 · 94,7%** | **69,2%** | **8/25 · 32%** | 0/40 | **0,00723** |

**Mesmo modelo, mesmo custo, melhor em tudo.** +1 detecção recuperada, −2 falsos
positivos, baseline segue em zero. É um entregável independente da migração: se
confirmar em shadow, produção adota o V4 agora, sem trocar de modelo.

⚠️ N pequeno: "+5,2 pp" são 17→18 detecções. E o prompt foi escrito **olhando este
dataset**, então parte do ganho pode ser ajuste, não generalização. Validar em shadow
antes de creditar.

---

## Resultado 2 — o V4 QUEBRA os open-weight

O mesmo prompt que ajustou o Gemini de leve mordeu forte nos open-weight, invertendo o
problema: no Camp 48 eles disparavam demais (FP 64-100%); agora **não disparam**.

| braço | n | erros | recall/det | precisão | FP | base | $/ev |
|---|---|---|---|---|---|---|---|
| kimi `v4_single` | 122 | 0 | **19/19 · 100%** | 57,6% | 48% | 5% | 0,00657 |
| **`current_v4`** | 122 | 0 | 18/19 · 94,7% | **69,2%** | 32% | 0% | 0,00723 |
| `current_v1` | 122 | 0 | 17/19 · 89,5% | 63,0% | 40% | 0% | 0,00725 |
| kimi `v4_casc_5f` | 122 | 0 | 14/19 · 73,7% | 73,7% | 20% | 0% | 0,00443 |
| kimi `v4_casc` | 122 | 0 | 12/19 · 63,2% | **85,7%** | 4% | 2% | 0,00554 |
| qwen `v4_casc_5f` | 106 | 16 | 6/16 · 37,5% | 100,0% | 0% | 0% | 0,00271 |
| magistral `v4_casc` | 122 | 0 | 7/19 · 36,8% | 77,8% | 8% | 0% | 0,00382 |
| magistral `v4_single` | 122 | 0 | 7/19 · 36,8% | 77,8% | 8% | 0% | 0,00489 |
| magistral `v4_casc_5f` | 122 | 0 | 5/19 · 26,3% | 71,4% | 8% | 0% | 0,00229 |
| qwen `v4_casc` | 105 | 17 | 4/17 · 23,5% | 100,0% | 0% | 0% | 0,00350 |
| qwen `v4_single` | 42 | 80 | 1/6 · 16,7% | 100,0% | 0% | 0% | 0,00486 |

**Nenhum braço open-weight fecha recall ≥85% E precisão ≥69,2%.** O melhor
(`kimi:v4_casc_5f`) supera a precisão do controle (73,7% vs 69,2%) mas perde **21 pp de
recall**. O `qwen` chega a 100% de precisão sem errar um negativo sequer — e acha só 1/4
dos descartes.

---

## Resultado 3 — a hipótese central do plano estava ERRADA

O plano assumia que "o gate barra porque vê pouco" e propunha triplicar os frames
(5→15, medido como mais barato em baixa resolução). O par de braços que só difere nisso:

| kimi | recall/det | precisão | FP |
|---|---|---|---|
| gate 5 frames | **73,7%** | 73,7% | 20% |
| gate 15 frames | 63,2% | **85,7%** | 4% |

**Mais frames deixa o gate mais conservador, não mais sensível.** Em retrospecto faz
sentido: com 15 frames ele vê mais quadros sem deposição e conclui que não houve
flagrante. O gate barra por **critério**, não por falta de evidência — e o lever de
frames é um controle de precisão, não de recall.

---

## Resultado 4 — o gate é o que não dá para substituir

Simulação offline das 9 cascatas heterogêneas (grátis: os braços `single` rodaram o
detail nos 122 eventos) + varredura do limiar de gate de 1 a 85:

**Apenas 4 combinações fecham recall ≥85% e precisão ≥69,2% — e as 4 usam gate Gemini:**

| gate | detail | recall/det | precisão |
|---|---|---|---|
| `current_v4` ≥85 | **kimi-k2.5** | 18/19 · 94,7% | 69,2% |
| `current_v1` ≥85 | **kimi-k2.5** | 18/19 · 94,7% | 69,2% |

**O detail do kimi é tão bom quanto o do Gemini** — com gate Gemini ele reproduz
exatamente o desempenho do `current_v4`. O que nenhum open-weight substitui é o **gate**.
E gate Gemini é justamente o que deixa de existir em 16/out.

A varredura de limiar confirma por quê: no kimi, baixar o limiar de 85 para 1 **não muda
nada** (19/19 em todos). A confiança do gate dele é binária (0 ou ≥85) — não tem poder
discriminativo para calibrar.

---

## Resultado 5 — disponibilidade de endpoint é critério de seleção

93 erros, **todos do `qwen3-vl-235b`**: `ServiceUnavailableException` e
`ConnectionClosedError`, com 5 retentativas e backoff exponencial insuficientes.

| braço | erros |
|---|---|
| qwen `v4_single` | 80/122 (**66%**) |
| qwen `v4_casc` | 17/122 |
| qwen `v4_casc_5f` | 16/122 |
| kimi + magistral (6 braços) | **0** |

Com 66% de perda, os números do qwen não são amostragem aleatória — estão marcados e não
entram em comparação de igual para igual. Somando as duas campanhas, **3 dos 6
open-weight testados (nemotron, palmyra, qwen) ficaram indisponíveis em algum momento em
24 h**; Gemini, kimi e magistral não tiveram um único erro em ~2.900 chamadas.

Para um Plano B que precisa rodar 24/7 a partir de outubro, isso é critério de seleção.

---

## Resultado 5 revisitado — o re-teste (30/07, 21h30–22h35 BRT)

O Resultado 5 acima tinha **duas falhas de desenho**, encontradas na releitura do log
(`.tmp_fase2_bedrock.log`) e do CSV bruto:

1. **Não existiu controle temporal.** Os 9 braços rodaram sequencialmente num único
   processo (`bench_bedrock.py:652`) e os três do qwen ocuparam o **terço final**
   (jobs 733–1098). kimi e magistral rodaram *antes*, em janela disjunta — nunca foram
   exercitados enquanto o qwen falhava. A frase "zero erros no mesmo período e mesma
   conta" **não estava estabelecida**.
2. **Os erros eram agrupados, não uniformes.** Por decil de ordem de conclusão, o
   `v4_casc_5f` falhou **13 de 13** no início e depois rodou **96 eventos consecutivos
   com zero erro** — mesmo endpoint, mesmo payload.

O re-teste (`scripts/probe_qwen_availability.py`) corrigiu as duas coisas: fila
**intercalada** com um modelo de controle e telemetria **por tentativa**
(`results/qwen_*_attempts.jsonl`).

### Fase A — sonda: 108 chamadas, ZERO erros

24 eventos estratificados com o payload de pior caso (`v4_single`), qwen intercalado com
`magistral-small` na razão 2:1, em três células:

| célula | região | workers | qwen | controle | erros | p50 qwen |
|---|---|---|---|---|---|---|
| A1 | us-east-1 | 3 | 24 | 12 | **0** | 12,1 s |
| A2 | us-east-1 | 1 | 24 | 12 | **0** | 13,5 s |
| A3 | us-west-2 | 3 | 24 | 12 | **0** | 16,0 s |

Custo real: **US$ 0,4951**. Concorrência não é a causa (w=1 e w=3 idênticos) e região não
é alavanca (as duas limpas). Critério pré-registrado (<5%) → liberada a Fase B.

(Os números por célula acima vêm dos CSVs `results/probe_A*.csv`. O `--summarize` daquela
rodada funde A1 e A2 numa linha só, porque a tag ainda não carregava a célula — corrigido
no script depois; como tudo deu zero, não muda nada.)

### Fase B — 366 chamadas: o episódio tem começo e fim MEDIDOS

| janela (UTC) | tentativas | falhas | taxa |
|---|---|---|---|
| 00:43–01:00 e 01:29–01:34 (fora) | 309 | **0** | **0,0%** |
| 01:00:25 – 01:28:53 (dentro) | 222 | 156 | **70,3%** |

O comportamento é **bimodal**: o endpoint está 100% saudável ou ~70% derrubado, sem
meio-termo. O episódio durou **28 minutos** (22:00–22:28 BRT). Exceções: 133
`ServiceUnavailableException` + 23 `InternalServerException`.

Erro **efetivo por evento**: **16/366 = 4,4%** — as retentativas absorveram quase tudo
(19% dos eventos precisaram de ≥2 tentativas, mediana de 25 s de relógio extra).
Recomputado sob o predicado de retentativa **antigo** do Camp 49: **também 4,4%** — não
houve `ConnectionClosedError` nesta rodada, então o conserto do predicado não maquiou o
número e a comparação com o Camp 49 é limpa.

### Qualidade com amostra COMPLETA

O Camp 49 mediu o qwen sobre um resíduo enviesado: no `v4_single` só **6 dos 40 baselines**
e 10 dos 35 tp completaram. Agora, com 115–119 dos 122:

| braço | rodada | n | err | recall/det | precisão | fp/det | baseline | $/ev | p50 | p90 |
|---|---|---|---|---|---|---|---|---|---|---|
| `v4_single` | Camp 49 | 42 | 80 | 1/6 · 16,7% | 100% | 0/14 | 0/6 | 0,00486 | 23,4 s | 108,2 s |
| | **re-teste** | 115 | 7 | **7/19 · 36,8%** | **100%** | **0/25** | **0/35** | 0,00466 | **16,4 s** | **24,6 s** |
| `v4_casc` | Camp 49 | 105 | 17 | 4/17 · 23,5% | 100% | 0/24 | 0/37 | 0,00350 | 21,2 s | 69,6 s |
| | **re-teste** | 119 | 3 | **6/19 · 31,6%** | **100%** | **0/25** | **0/38** | 0,00365 | 12,1 s | 28,6 s |
| `v4_casc_5f` | Camp 49 | 106 | 16 | 6/16 · 37,5% | 100% | 0/19 | 0/40 | 0,00271 | 8,1 s | 26,2 s |
| | **re-teste** | 116 | 6 | **6/19 · 31,6%** | **100%** | **0/25** | **0/36** | 0,00270 | 8,4 s | 28,9 s |

**A conclusão do Camp 49 se mantém, mas por outro motivo.** O qwen não é "inavaliável":
é um modelo **hiperespecífico e de recall baixo** — 100% de precisão, **zero falso
positivo em 25 detecções FP e zero disparo em 35–38 baselines**, com recall de 31,6–36,8%.
Empata em recall com o magistral (7/19) e o supera em precisão (100% vs 77,8%). Segue a
**~50 pp do recall necessário** (≥85%), então continua fora como substituto do gate — mas
agora descartado por **qualidade medida**, não por indisponibilidade.

A latência também era artefato do episódio: p90 caiu de **108,2 s para 24,6 s**.

### O que isso muda no critério de seleção

Disponibilidade deixa de ser critério binário e vira **risco quantificado**: episódios de
~30 min com ~70% de perda, contra os quais 5 retentativas com backoff de ~90 s absorvem
~95% dos eventos. Para o SAÍRA (event-driven, sem SLA de segundos) isso é tolerável; o
que não é tolerável é o recall. **Nada disso reabilita o qwen — só move o motivo da
rejeição.**

Correção de harness aplicada: `_RETRYABLE` (`_bedrock_client.py`) não incluía
`ConnectionClosedError`/`EndpointConnectionError`/`ReadTimeoutError`/`ConnectTimeoutError`,
então 9 dos 93 erros do Camp 49 voltaram sem nenhuma retentativa. Corrigido, com
`_RETRYABLE_CAMP49` preservado para replay honesto.

Custo do Tema 1: **US$ 1,778** (Fase A 0,495 + Fase B 1,283), medido dos tokens crus.

---

## Decisão

**1. ADOTAR o prompt V4 em produção** (após shadow) — ganho grátis no pipeline atual:
recall 89,5→94,7%, precisão 63,0→69,2%, custo idêntico. Promover
`_prompts_v4picam.py` → `worker/_prompts_v4.py`, ativável por `GEMINI_PROMPT_VERSION=v4`.

**2. NÃO migrar para open-weight.** Duas campanhas, 2.700+ chamadas, 24 braços: nenhum
fecha recall e precisão simultaneamente. O diagnóstico agora é preciso — **o detail é
substituível (kimi empata com o Gemini), o gate não é.**

**3. O Plano B para 16/out segue sendo o Gemini-3 `unified_low_2s`**, e o V4 deve ser
testado sobre ele — é a próxima campanha óbvia: se o V4 melhora o 2.5 sem custo, é
plausível que melhore o 3.1-flash-lite também, e aí o Plano B fica melhor que o atual.

## Caveats

- **N pequeno**: 19 detecções TP. Uma detecção = 5,3 pp de recall.
- O V4 foi escrito olhando este dataset — risco de ajuste. Validar em shadow.
- Os números do `qwen` têm 13-66% de perda por indisponibilidade; não são comparáveis.
- A reclassificação da Fase 0 alterou o dataset oficial: campanhas 47 e 48 devem ser
  lidas com os rótulos antigos (backup em `manifest.csv.bak-20260730`).
- `baseline_fire` não foi critério de aprovação: o conjunto é "o que o 2.5 rejeitou",
  circular por construção.
- Custo estimado dos tokens; reconciliação com o Cost Explorer pendente (≥24 h).
