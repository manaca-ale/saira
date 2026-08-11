# Handoff — Campanhas de benchmark do SAÍRA

> Documento de passagem de responsabilidade das campanhas de benchmark (maio–agosto/2026).
> Fonte de verdade dos resultados: [`benchmarks/SUMMARY.md`](../benchmarks/SUMMARY.md) (índice mestre, 1 linha por campanha).
> Última atualização: 2026-08-11.

## 1. Visão geral

As campanhas de benchmark são experimentos offline que medem o pipeline de detecção de descarte irregular (gate → detail → filtros CV) contra datasets rotulados, antes de qualquer mudança chegar à produção. Cada campanha vive em `benchmarks/campaigns/NN-slug-YYYY-MM-DD/` com relatório, runner, config e resultados. **Nenhuma mudança de prompt, modelo, threshold ou filtro entra em produção sem campanha que a justifique.**

Papel no roadmap: o Gemini 2.5 será depreciado em **16/out/2026** — a série de campanhas 47–52 (migração para Gemini 3 / open-weight via Bedrock) é o trabalho mais crítico em andamento.

### Mapa de câmeras

| device_id | Local | Apelido interno | Notas |
|---|---|---|---|
| `esp32_001` | Imbiribeira | cam_10 | DINOv2 em shadow |
| `esp32_002` | Mangabeira | cam_11 | Câmera mais cara (46% da conta Gemini); dual-gate V3+B3; structural-delta em enforce; BGSUB em shadow |
| `esp32_003` | Boa Viagem (Sá e Souza 1415) | id=12 | Reinstalada 23/07 |
| `esp32_004` | Irmã Dora / Imbiribeira | — | ⚠️ Sem enviar frames desde 23/07 |
| `esp32_005` | Arruda | cam_14 | BGSUB recal diária + adaptive clean-zone (shadow) |
| `pi-cam-001` | Via Mangue III-2 / Imbiribeira | id=15 | Event-driven (BGSUB no Pi + clipe); alvo das camps 47–52 |

## 2. Metodologia

### Como criar uma campanha

Processo de 5 passos descrito em `benchmarks/SUMMARY.md` (seção "Como adicionar uma nova campanha"):

1. Criar pasta `campaigns/NN-titulo-curto-YYYY-MM-DD/` (próximo número sequencial).
2. Copiar `benchmarks/_template.md` para `campaigns/NN-.../report.md` e preencher.
3. Salvar runners, JSONs e logs na mesma pasta (`scripts/`, `results/`).
4. Acrescentar uma linha em `SUMMARY.md` **e** em `summary.csv`.
5. Referenciar o dataset usado (`data/datasets/official/` ou `legacy/`).

### 🚨 Regra de ouro: paridade com produção

**As campanhas 20 e 21 foram INVALIDADAS** por sub-amostragem de frames e reimplementação do pós-processamento fora do worker. A lição está codificada assim:

- O runner **importa o código real do worker** (`services/yolo-worker-vm/src`) — nunca reimplementar gate/detail/pós-processamento no script do benchmark.
- Todo desvio inevitável do prod vira um bloco `known_deviation` explícito no `run-config.yaml`.
- **Modelo a seguir**: `campaigns/52-gate-prompt-v1-vs-v3-cost-2026-08-04/` — `run-config.yaml` com blocos `prod_parity`, `auth`, `pricing`, `decision_rule` e `known_deviation`; o runner valida fidelidade comparando tokens/prompt medidos vs prod.
- Config real de prod hoje: thinking budget **2048** (1024 foi testado e revertido), `GEMINI_CASCADE_MAX_FRAMES=48` global, espaçamento **uniforme** de frames no gate (o `_mid()` 25/50/75 da camp 44 está desatualizado).

### Armadilhas de medição conhecidas

- **Custos Gemini 3**: SOMAR thinking tokens (cobrados como output, ~3,3k tok/ev); imagem no G3 custa 3,5× o G2.5. A camp 48 descobriu que o runner da 47 usava preço errado do `2.5-flash` — preço canônico está em `detector_gemini._MODEL_PRICES`.
- **Custo real de prod** = US$ 0,00135/evento (metodologia validada contra o BigQuery billing export a ±0,5% via tabela `gemini_call_log` — não precisa de API key por câmera).
- **Gate não é reproduzível**: positivos do gate Gemini 3.1 só reproduzem ~50% em replay; Vertex ≠ AI Studio. Não tratar replay offline como verdade absoluta (é direcional, ~68% na camp 37).
- **Avaliar sempre contra o status do OPERADOR** (`detections.status` no DB), não contra `prod_created_detection` — a camp de avaliação dos shadows (04/08) mostrou que usar o campo errado **inverte a conclusão**. Operador rejeita ~61% do que o pipeline confirma.
- **Frames de prod D-1 rotacionam para o S3** (`saira-images`, sa-east-1) às 03h BRT — dataset building que depende de frames "de ontem" precisa puxar do S3, não do volume.
- **Timezone**: no DB, `timestamp` é naive Brasília (UTC-3) e `created_at` é UTC. Filtros de tempo usam `created_at`.

## 3. Como rodar

### Autenticação e ambiente

| Recurso | Config |
|---|---|
| Vertex AI (Gemini) | Projeto GCP **`saira-tests-260520`** via ADC keyless: `gcloud auth application-default login`. Billing = conta **Testes** (`0149F3`) — nunca rodar bench na conta Produção. |
| Env compartilhado | `services/.env.benchmark` (gitignored): `GEMINI_USE_VERTEX`, `GCP_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GEMINI_TEST_API_KEY`. Algumas campanhas têm `.env.benchmark` próprio na pasta (também gitignored — pedir ao Alexandre se precisar dos históricos). |
| AWS Bedrock (camps 42/48/49/51) | Perfil AWS **`codex-ops`**, região `us-east-1`. Teto de payload: corpo de 4 MB (~2,7 MB de imagem). |
| AI Studio | Key em `GEMINI_TEST_API_KEY`; ⚠️ key de AI Studio não roda em projeto GCP novo, e resultados divergem do Vertex (ver "gate não reproduzível"). |

### Executando

Não há runner central — cada campanha tem o seu (`scripts/bench_*.py` ou `bench_*.py` na raiz da pasta). Padrão típico:

```bash
cd benchmarks/campaigns/52-gate-prompt-v1-vs-v3-cost-2026-08-04
python scripts/bench_gate_prompt_cost.py --arm A_prod   # lê run-config.yaml e .env
python scripts/agg_all.py                               # agrega results-*.json
```

⚠️ Portabilidade (débito conhecido): os runners hardcodam `c:\saira` como raiz do projeto, e `c:\saira\data` é um **symlink para `D:\saira\data`**. Em outra máquina, recriar a mesma topologia (ou editar `PROJECT_ROOT`/`DATASET_ROOT` no runner).

Runners legados (camps 02–06, pastas perdidas): `services/benchmark_*.py`. Ferramentas ad-hoc: `tools/` (`bgsub_bench_replay.py`, `polygon_marker.html`, `tp_marker.html` etc.).

## 4. Dataset oficial

`data/datasets/official/` (**gitignored**, ~1,8 GB, 22,7k JPGs) — backup no Drive (ver §8).

- **Ground truth** = `manifest.csv` (653 eventos: 129 TP · 398 FP · 79 indefinido · 7 missed · 40 baseline). Fonte primária dos rótulos = planilha Google **"Mapeamento de Ocorrências"** (ID `1wABg4qMYFR5IHG0lWlj0CBhL2jm5c_ARJQjdDXpvqko`).
- Estrutura: `cam_<nome>/{tp,fp,indefinido,missed,baseline}/<event_id>/{frames/*.jpg, label.json}`. Ver `data/datasets/official/README.md` (schema completo).
- **Reconciliação**: `benchmarks/scripts/rebuild_official_manifest.py` (`--dry-run` → `manifest.rebuilt.csv`; `--apply` faz backup e sobrescreve). É aditivo e não-destrutivo. ⚠️ Re-rodar após merges de eventos novos; usar event_id único **por câmera** (rebuild antigo indexava global e colidiu na Boa Viagem).
- 🚨 **O dataset NÃO é reconstruível do zero**: os scripts `build_official_datasets.py` e `build_events_manifest.py` citados no README **não existem no repo** (perdidos). Só existe a reconciliação. O tarball no Drive é o backup — trate-o como insubstituível.
- Legado (`data/datasets/legacy/`): read-only, camps 02–06, não usar em testes novos.

## 5. Estado atual e decisões-chave por linha de trabalho

Resumo do que já foi decidido — **antes de propor um experimento, verificar aqui se ele já foi tentado e reprovado**. Detalhes e números em `SUMMARY.md`.

### Migração 16/out (camps 47–52) — PRIORIDADE

- **O gate é o gargalo, o detail é substituível** (camp 49): gate Gemini + detail kimi reproduz o pipeline atual; nenhuma combinação sem gate Gemini fecha recall ≥85% com precisão ≥69%.
- **Prompt V4** (flagrante + catador) melhora o pipeline ATUAL de graça: recall 89,5→94,7%, precisão 63→69,2%, custo idêntico. **Pendente shadow + deploy.**
- **Não migrar drop-in para Gemini 3** (camp 47): substitutos regridem recall (−25pp) com o prompt V1 atual. Recalibrar prompt antes.
- **Não migrar para open-weight** (camps 48/49): nenhum braço domina o controle; qwen rejeitado por recall (37%, disponibilidade bimodal no Bedrock); Llama 4 eliminado (teto de 3 imagens).
- **Self-host perde por 8–12×** (dimensionamento Tema 2): alvo real US$ 1.278/mês para 100 câmeras; pico = 6,5× a média.
- **Gate barato confabula** (camp 51): 3.1-flash-lite recupera 6 dos 7 TPs que o gate de prod perde — é o candidato de gate para a migração (shadow C51).

### Shadows em produção

- **Shadow C51 ATIVO na pi-cam-001** desde 04/08: gates candidatos 3.1-flash-lite + magistral (g3) → kimi no detail (PR #80). US$ 0,0028/janela. **Revisão marcada: 11/08.**
- Shadows anteriores (Gemini 3.1 e Bedrock kimi) foram avaliados contra o operador e **desligados em 04/08**. Ao avaliar, filtrar o ledger por `prompt` e cruzar com `detections.status`.

### Mangabeira / FP (cam_11) — NÃO re-tentar

16 campanhas consolidadas (22–24, 32, 40, 42, 43 etc.). Vereditos fechados:

- ❌ Prompt-tuning do detail, DINOv2 (colapsa em N grande, AUC 0,55 = overfit do dataset curado), heurística de volume, screener LLM (Gemini e Haiku destroem recall em enforce), cláusula bulky.
- ✅ Único avanço: **structural-delta** (census micro-tiles before/after, camp 41, AUC 0,827 estável em holdout) + gate barra-alta. `STRUCTURAL_RECOVERY_MODE=enforce/thr=8` em prod desde 03/07 (PR #49).
- Pile-crops em prod desde 30/05 (`GEMINI_DETAIL_PILECROP_ENABLED=true`, só esp32_002).
- Dual-gate V3+B3 em prod desde 28/05; camp 52 confirmou que o **addon de 540 tokens vale +24pp de recall** — não "simplificar" o prompt.

### BGSUB

- Prod desde 23/05 (`BGSUB_PREFILTER_ENABLED=true`).
- **Arruda (esp32_005)**: baseline semanal apodrece em horas → recalibração DIÁRIA (camp 39, PR #39) + adaptive clean-zone, em shadow.
- **Mangabeira: manter em SHADOW** — enforce economizaria R$ 225/mês mas custa −40% de recall; baixar threshold não resolve (cegueira em p≈0).
- Baseline `.npz` não se recria sozinho após outage — usar `calibrate_bgsub.py`.

### DINOv2

- Per-camera >> global. cam_10 separa (AUC 0,947); cam_11 não.
- ⚠️ **Enforce estático cegou a esp32_001** (zerou detecções desde 12/06) → papel correto é **shadow + retreino semanal** (drift temporal, camp 27/35).

### Gate / prompts por câmera

- V1 é cego a descarte a pé/carroça (o detail recupera 95%). V3+B3 só ajuda na Mangabeira; na Imbiribeira e Arruda **regrediu** (camps 30/34/37). Na Arruda, prompt SCRATCH (from-scratch) venceu V1 por pouco (camp 37c).
- Imbiribeira: gate veículo-focado reprovado (teto estrutural 60% de recall, camp 44); alavancas vivas = polígonos + DINOv2.

## 6. Pendências abertas (com data)

| Data | Pendência |
|---|---|
| **11/08** | Revisar shadow C51 (pi-cam-001): comparar gates candidatos vs operador, decidir gate da migração |
| ~16/08 | Revisar efeito acumulado BGSUB-enforce + recall Mangabeira (camp 52 achou 60% no melhor braço) |
| antes de 16/10 | Shadow + deploy do prompt V4; decidir modelo pós-Gemini-2.5 (fluxo: V4 sobre `unified_low_2s` do G3) |
| — | esp32_004 sem frames desde 23/07 (visita de campo pendente) |
| — | Recriar `build_official_datasets.py` (débito; ver §4) |

## 7. Checklist de acessos para o novo responsável

- [ ] **GitHub** — repo `manaca-ale/saira` (branches: `develop` = deploy no TEST, `main` = PRODUÇÃO; nunca push direto na main).
- [ ] **GCP** — projeto `saira-tests-260520` (Vertex AI) com ADC; opcionalmente leitura do BQ billing export (projeto Flora, só conta Produção).
- [ ] **AWS** — perfil `codex-ops` (Bedrock us-east-1) para benchmarks open-weight.
- [ ] **Google Sheet** — "Mapeamento de Ocorrências" (`1wABg4qMYFR5IHG0lWlj0CBhL2jm5c_ARJQjdDXpvqko`), fonte primária de rótulos.
- [ ] **Drive** — pasta "SAÍRA — Benchmarks Handoff" (tarballs de artefatos + dataset, ver §8).
- [ ] **SSH `saira-prod`** (EC2 us-east-1) — necessário para montar datasets novos (pulls SQL, frames no volume Docker, S3). Test e prod na MESMA instância; usar `-p saira-test`/`-p saira-prod` no compose.
- [ ] **Frontend de teste** — https://test-saira.manaca.tech (admin@saira.com / admin123).

## 8. Artefatos grandes (fora do git)

O git guarda relatórios, runners, configs e resultados (~50 MB). Frames, modelos MOG2 (`.npz`) e corpora pesados (~6,5 GB) ficam fora:

- **Original**: máquina do Alexandre — `c:\saira\benchmarks\campaigns\` (pastas pesadas: camps 19, 33, 36, 39, 40, 44, 45) e `D:\saira\data\datasets\official\`.
- **Backup / transferência**: Google Drive, pasta **"SAÍRA — Benchmarks Handoff"**:
  - `benchmarks-campaigns-20260811.tar.gz` — árvore completa de `campaigns/` (sem arquivos `.env*`).
  - `dataset-official-20260811.tar.gz` — `data/datasets/official/` completo.
  - `SHA256SUMS.txt` — conferir integridade após download (`sha256sum -c SHA256SUMS.txt`).
- Restore: extrair o dataset em `<repo>/data/datasets/official/` (ou ajustar `DATASET_ROOT` nos runners) e as campanhas por cima de `benchmarks/campaigns/` (o git já tem os arquivos leves; o tarball adiciona os pesados).

## Débitos conhecidos (fora de escopo deste handoff)

- Recriar `build_official_datasets.py` / `build_events_manifest.py` (rebuild do dataset do zero).
- Tornar os runners portáveis (remover hardcode `c:\saira`).
- Migrar artefatos do Drive para S3 com versionamento.
- Campanhas 02–05 e 07: pastas perdidas (existem só as linhas no `SUMMARY.md` e os runners legados em `services/`).
