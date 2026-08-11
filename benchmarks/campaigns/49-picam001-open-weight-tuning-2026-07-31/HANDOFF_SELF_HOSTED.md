# HANDOFF — Self-hosted open-weight: dimensionamento e custo (100 câmeras)

> Sessão paralela ao shadow do kimi (`HANDOFF_SHADOW_KIMI.md`). Três temas, um por vez.
> Contexto medido nos Camps 48/49 — não refazer o que já está aqui.

## Tema 1 — RESOLVIDO em 30/07 (21h30–22h35 BRT) ✅

> Executado. Detalhe completo em `report.md` → "Resultado 5 revisitado".
> Instrumento: `scripts/probe_qwen_availability.py`. Custo real: **US$ 1,778**.

**Veredito: a indisponibilidade era EPISÓDICA, e o qwen segue rejeitado — por recall.**

1. **Duas falhas no desenho original**, achadas antes de gastar: (a) *não existiu controle
   temporal* — os 9 braços rodaram sequencialmente e os 3 do qwen ocuparam o terço final,
   então kimi/magistral **nunca** rodaram na mesma janela (a premissa "zero erros no mesmo
   período" era inferência, não medição); (b) os erros eram **agrupados**, não uniformes —
   o `v4_casc_5f` falhou 13/13 no início e depois rodou 96 eventos seguidos sem erro.
2. **Fase A (sonda intercalada, 108 chamadas): ZERO erros**, em us-east-1 e us-west-2,
   com workers 1 e 3. Concorrência não é a causa; região não é alavanca.
3. **Fase B (366 chamadas): comportamento BIMODAL.** Fora do episódio, 309 tentativas e
   **0,0%** de falha. Dentro (01:00:25–01:28:53 UTC, **28 min**), 222 tentativas e
   **70,3%**. Erro efetivo por evento: **4,4%** (16/366) — idêntico sob o predicado de
   retentativa antigo, então a comparação com o Camp 49 é limpa.
4. **Qualidade com amostra completa** (o Camp 49 avaliou o qwen sobre 6 de 40 baselines):
   recall **31,6–36,8%**, precisão **100%**, **0/25** FP, **0/35–38** baseline. Ele empata
   com o magistral em recall e o supera em precisão — e continua ~50 pp abaixo dos 85%
   necessários. p90 caiu de 108,2 s para 24,6 s (a latência alta era o episódio).

**Consequência para os temas 2 e 3:** disponibilidade deixa de ser critério eliminatório
e vira risco quantificado (episódios de ~30 min, ~70% de perda, absorvidos a ~95% por 5
retentativas). O que elimina o qwen é o recall. E, para o tema 3, o ponto do usuário fica
mais forte: o **magistral** entrega o mesmo recall do qwen (7/19) sendo o único
hospedável em 1 GPU.

<details>
<summary>Instruções originais do Tema 1 (mantidas para histórico)</summary>

### Tema 1 — Re-testar o `qwen3-vl-235b` (falhas podem ter sido temporárias)

**O que aconteceu (30-31/07):** 93 erros, **todos do qwen** — `ServiceUnavailableException`
e `ConnectionClosedError`, com 5 retentativas e backoff exponencial insuficientes.
Perda de 13% (`v4_casc`), 13% (`v4_casc_5f`) e **66%** (`v4_single`). Kimi, magistral e
Gemini: **zero erros** em ~2.900 chamadas no mesmo período e mesma conta.

**Por que não descartar:** os números de qualidade dele eram os melhores em
especificidade — **100% de precisão, zero falso positivo em 19-24 detecções FP e zero
baseline-fire** — só que com recall de 23-37%. Se a indisponibilidade era transitória, ele
volta a ser candidato (com o problema de recall, que é outro assunto).

**Como re-testar (barato, ~US$ 0,50):**

```bash
aws sso login --profile codex-ops          # a sessão expira; renove antes de tudo
cd benchmarks/campaigns/49-picam001-open-weight-tuning-2026-07-31
python scripts/bench_bedrock.py --arms qwen3-vl-235b:v4_single --tag qwen_retry --workers 2
python scripts/agg_all.py --csv results/bench_v4_qwen_retry.csv
```

Rodar com **`--workers 2`** (não 4): parte dos 503 pode ter sido concorrência.
O runner é resumível (`done_keys`), então dá para rodar em pedaços.

**Critério:** se a taxa de erro cair abaixo de 5%, o qwen volta à mesa e os números de
qualidade dele passam a valer. Se repetir >20%, é limitação estrutural de capacidade do
endpoint para esse modelo, e aí a conclusão do Camp 49 se confirma.

**Registrar de qualquer forma:** rodar em horário diferente do original (a rodada foi
~11h-13h BRT de 30-31/07) para separar "modelo sem capacidade" de "pico de demanda".

</details>

---

## Tema 2 — RESOLVIDO em 30–31/07 ✅

> Análise completa em **[`TEMA2_DIMENSIONAMENTO.md`](TEMA2_DIMENSIONAMENTO.md)**.
> Custo: US$ 0 (só leitura de prod e das APIs de preço da AWS).

**Veredito: a 100 câmeras o self-host só ganha para o modelo que não faz o serviço.**

1. 🔴 **A linha de base deste handoff estava errada por 10×.** Medido em
   `gemini_call_log` (prod, 30 d, 34.774 eventos): **US$ 0,002204/evento** e
   **US$ 1.278/mês** para 100 câmeras — não US$ 0,00725 e US$ 13.050. Causa: o
   US$ 0,00725 é o custo de um evento que roda gate+detail, mas em produção só
   **3,8–9%** chegam ao detail. `pi-cam-001` também faz **300,7 ev/dia**, não ~600.
2. **Pico medido** (frota): p95 88/h, p99 230/h, **máx 313/h** ⇒ a 100 câmeras,
   **1,45 ev/s no pico** contra 0,22 de média — **6,5×**. Concentrado às 16h–18h e
   correlacionado entre câmeras.
3. **Preços medidos** (Pricing API + spot, us-east-1): RI de 1 ano sem entrada dá
   **35–37%** em toda a linha G. ⚠️ `g6e.xlarge` (L40S) **não tem desconto spot** —
   spot = on-demand, pinado. `p5.48xlarge` dá 62%.
4. **kimi e qwen perdem por 8–12×**: hospedar o kimi custa **US$ 15.321/mês** (8× H100,
   melhor caso spot) contra **US$ 1.278** de fatura. É consequência de MoE precisar de
   todos os pesos residentes — não tem ajuste de engenharia que feche.
5. **O magistral fecha a conta e não faz o serviço**: break-even em **71 câmeras**
   (`g6.xlarge` RI + N+1 + EBS + operação), mas 36,8% de recall contra 94,7%.
6. **O baseline pós-16/out é ainda mais apertado**: `gemini-3.1-flash-lite` já medido em
   shadow dá **US$ 0,001264/ev**, 8,5% mais barato que o 2.5.

**Lacuna assumida:** throughput por GPU não foi medido (decisão de não gastar em
instância). É **unidirecional** — só pode exigir MAIS GPUs, nunca menos ⇒ todas as linhas
são pisos de custo e a conclusão é robusta. Onde importaria é justamente na linha do
magistral (~US$ 3 para medir numa `g6.xlarge`).

<details>
<summary>Instruções originais do Tema 2 (mantidas para histórico)</summary>

### Tema 2 — Dimensionamento e custo self-hosted

### Carga medida (NÃO estimar — foi medido nos 122 eventos reais)

| modelo | tok_in (mediana) | tok_out | imagens | latência p50 | p90 |
|---|---|---|---|---|---|
| kimi-k2.5 | **9.130** | 492 | 23 | 12,4 s | 21,9 s |
| magistral-small | **9.561** | 290 | 23 | 15,2 s | 20,4 s |
| qwen3-vl-235b | 7.972 | 277 | 24 | **16,4 s** | **24,6 s** |

⚠️ A latência do qwen foi **corrigida no re-teste do Tema 1**: os 23,4 s / 109,3 s
originais vinham da amostra contaminada pelo episódio de indisponibilidade. Com 115
eventos limpos: **p50 16,4 s · p90 24,6 s**. Os tokens não mudaram (mediana 7.972 in nos
dois conjuntos). Use os números novos para dimensionar.

Imagens a 640 px q70 custam ~**324 tok/imagem** (kimi), ~345 (magistral), ~255 (qwen).
O input é **~90% imagem** — é isso que domina o dimensionamento, não o texto.

### Volume

- `pi-cam-001` (event-driven): **~600 eventos/dia** — confirmar no banco antes de fechar conta
- Cenário do usuário: **100 câmeras** → **60.000 eventos/dia** ≈ **0,7 evento/s** em média
- ⚠️ **Medir o PICO, não a média.** Descarte tem hora do dia; dimensionar pela média
  subdimensiona. Query sugerida: eventos/hora por câmera nos últimos 30 dias, pegar o p95.
- Volume diário de tokens a 100 câmeras: **~540 M tokens de input/dia** (60k × 9k) e
  ~24 M de output.

### A descoberta que decide o tema 3

**A ordem de qualidade é INVERSA à de viabilidade de self-host.** Verificar os tamanhos
(marcados como "conferir" — não confirmei nesta sessão):

| modelo | params (conferir) | VRAM fp16 | VRAM int8 | VRAM int4 | GPU mínima plausível |
|---|---|---|---|---|---|
| **magistral-small** | ~24 B denso | ~48 GB | ~24 GB | ~12 GB | **1× L40S 48 GB** ou 1× A10G 24 GB em int8 |
| **qwen3-vl-235b-a22b** | 235 B total / 22 B ativos (MoE) | ~470 GB | ~235 GB | ~118 GB | **2× H100 80 GB** em int4 (apertado) ou 4× A100 80 GB |
| **kimi-k2.5** | ~1 T total / ~32 B ativos (MoE) | ~2 TB | ~1 TB | ~500 GB | **8× H100 80 GB** |

MoE **não** ajuda em memória: os pesos todos precisam estar residentes, só o *compute*
por token é que usa poucos especialistas. Por isso o qwen-235B e o kimi-1T são caros de
hospedar apesar de ativarem 22-32 B.

**Consequência direta:** o kimi, que venceu no benchmark, é o **menos** hospedável.
O magistral, que perdeu, é o único que roda em uma GPU só. É exatamente o ponto do
usuário no tema 3 — vale investir em consertar o magistral.

### O que ir buscar (não tenho — SSO expirou)

**1. Preço real das instâncias GPU** via Pricing API na conta `codex-ops`:

```python
import boto3, json
p = boto3.Session(profile_name='codex-ops', region_name='us-east-1').client('pricing', region_name='us-east-1')
for it in ['g5.xlarge','g5.12xlarge','g6e.xlarge','g6e.2xlarge','g6e.12xlarge',
           'p4d.24xlarge','p5.48xlarge']:
    pg = p.get_products(ServiceCode='AmazonEC2', Filters=[
        {'Type':'TERM_MATCH','Field':'instanceType','Value':it},
        {'Type':'TERM_MATCH','Field':'regionCode','Value':'us-east-1'},
        {'Type':'TERM_MATCH','Field':'operatingSystem','Value':'Linux'},
        {'Type':'TERM_MATCH','Field':'tenancy','Value':'Shared'},
        {'Type':'TERM_MATCH','Field':'preInstalledSw','Value':'NA'},
        {'Type':'TERM_MATCH','Field':'capacitystatus','Value':'Used'}], MaxResults=1)
    ...
```

Comparar **on-demand vs Savings Plan de 1 ano vs Spot**. Para carga 24/7 previsível,
Savings Plan costuma ser a opção certa — e o SAÍRA é exatamente isso.

**2. Throughput real por GPU.** É o número que falta e **não dá para estimar com
honestidade** — depende de engine (vLLM/TGI/SGLang), quantização, batching e do custo de
prefill de imagem. O caminho: subir uma instância, servir o `magistral-small` em vLLM e
medir **eventos/s com o payload real** (23 imagens a 640 px, ~9,5k tokens). Uma tarde de
trabalho responde o dimensionamento inteiro.

Atalho para a conta: `instâncias = ceil(eventos_pico_por_s / throughput_medido_por_GPU)`,
com +1 de redundância (o SAÍRA não pode ficar sem inferência).

**3. Não esquecer no TCO** — o custo não é só a GPU:
   - EBS (modelo de 24 B em int8 ≈ 24 GB em disco; 235 B ≈ 235 GB)
   - transferência de dados (as imagens vêm das câmeras)
   - **operação**: quem faz patch, monitora OOM, recupera de falha. O Bedrock inclui isso.
   - ociosidade: 0,7 ev/s de média com picos significa GPU parada boa parte do dia,
     enquanto o Bedrock só cobra o que usa

### Referência de custo gerenciado (medido, para comparar)

| | por evento | 100 câmeras/mês (60k ev/dia) |
|---|---|---|
| **prod hoje** (Gemini-2.5, V1) | US$ 0,00725 | ~US$ 13.050 |
| kimi `v4_single` (Bedrock) | US$ 0,00657 | ~US$ 11.830 |
| magistral `v4_single` (Bedrock) | US$ 0,00489 | ~US$ 8.800 |
| magistral `v4_casc_5f` (Bedrock) | US$ 0,00229 | ~US$ 4.120 |

**É esse o número a bater.** Self-host só se paga se ficar confortavelmente abaixo — e a
conta tem que incluir operação, não só a instância. A pesquisa antiga
(`research_vlm_internalization`) apontava break-even em 40-70 câmeras; **essa estimativa
precisa ser refeita**, porque o custo do gerenciado caiu (open-weight no Bedrock é bem
mais barato que o Gemini) e porque o custo de prod estava subestimado em ~7×.

</details>

---

## Tema 3 — Comparativo self-hosted entre os três

A pergunta do usuário: *o magistral vale ser consertado, já que é o mais barato de
hospedar?*

**O que já se sabe (Camp 49, não refazer):**

| modelo | recall/det | precisão | veredicto de qualidade |
|---|---|---|---|
| kimi `v4_single` | 19/19 · **100%** | 57,6% | melhor recall, o único que acha tudo |
| magistral `v4_casc`/`v4_single` | 7/19 · **36,8%** | 77,8% | **colapsou** |
| qwen `v4_single` | 7/19 · **36,8%** | **100,0%** | **re-medido no Tema 1** (n=115): hiperespecífico, 0/25 FP e 0/35 baseline — mesmo recall do magistral, precisão maior. Já não é "inavaliável"; é recall insuficiente. |

**Diagnóstico do magistral (medido):** `casc` e `single` dão **exatamente o mesmo
resultado** (7/19) ⇒ o gate dele não filtra nada. E a confiança do gate responde **95 em
108 de 122 eventos** (só 3 valores distintos no total) ⇒ calibração degenerada, um
limiar não separa nada.

**O que NÃO tentar** (já medido, custou dinheiro):
- limiar de gate/detail — a confiança não discrimina
- mais frames no gate — deixa **mais** conservador, não mais sensível
- cascata heterogênea — as 9 combinações estão simuladas em `results/`
- filtro CV para os FPs — duração dos alarmes falsos é 108 s vs 107 s dos descartes reais

**O que ainda não foi tentado com o magistral:**
1. **Few-shot no prompt** — hoje o V4 descreve catador de forma abstrata. Existem
   6 exemplos de catador rotulados por humano (Fase 0) + 35 TPs. É a alavanca mais
   promissora e quase de graça.
2. **Prompt entre V1 e V4** — o V4 foi calibrado no Gemini e derrubou o recall dos
   open-weight de 94% para 37%. Um meio-termo pode existir.
3. **Fine-tune / LoRA** — só faz sentido no cenário self-hosted, e é justamente o
   argumento mais forte a favor dele: **um 24 B afinado nos 122 eventos rotulados pode
   superar um 1 T genérico nesta tarefa específica**. Não dá para fazer isso no Bedrock
   gerenciado.

**Recomendação de sequência:** medir o throughput do magistral em 1 GPU (tema 2) ANTES
de investir em qualidade. Se o custo self-hosted não fechar nem para ele, os temas 1 e 3
viram acadêmicos e a decisão volta para o gerenciado.

---

## Contexto essencial (para não repetir erro)

- **Custo real de prod = US$ 0,00725/evento**, não os US$ 0,00099 do Camp 47 (tabela de
  preço errada: `2.5-flash` é (0,30/2,50), não (0,15/0,60), e *thinking* é cobrado como
  output). Toda conta de break-even feita antes de 30/07 está errada.
- **Teto de payload do Bedrock = corpo de 4 MB** (~2,7 MB de imagem crua). Não vale para
  self-host, onde o limite é a VRAM — self-host pode mandar a janela em resolução
  original, o que talvez **melhore** a qualidade e muda a conta de tokens.
- Dados, scripts e resultados: `benchmarks/campaigns/49-picam001-open-weight-tuning-2026-07-31/`
  (`report.md`, `results/bench_v4.csv`, `scripts/_bedrock_client.py`).
- Camps 48 e 49 na memória: `project_camp48_bedrock_oss_vlm_2026-07-30`,
  `project_camp49_open_weight_gate_bottleneck_2026-07-31`.
