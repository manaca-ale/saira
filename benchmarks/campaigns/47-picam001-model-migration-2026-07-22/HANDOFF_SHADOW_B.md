# HANDOFF — Shadow B (structural-delta sozinho) na pi-cam-001

> Para retomar numa nova sessão. Campanha 47. Autoexplicativo. Tudo verificado em 22/07/2026.

## Contexto (o que já existe)

**Campanha 47** avalia migrar a pi-cam-001 dos modelos Gemini-2.5 (desligam 16/out/2026) para
`gemini-3.1-flash-lite`. Já concluído:
- Dataset oficial `data/datasets/official/cam_picam001/` (30 tp · 37 fp · 15 indefinido · 40 baseline).
- Benchmark: 3.1-lite low-res (`unified_low_2s` recall-first) = **93% recall ≈ 2.5**, custo neutro
  (~$0,0025/ev), mas **baseline-fire 15%** (FP em negativos verdadeiros → padrões catador/carroça,
  passante). Detalhes em `report.md`.
- **Shadow A (modelo 3.1) DEPLOYADO em prod** (log-only, `persist=False`): roda o cascade 3.1-lite
  paralelo na pi-cam-001, billing isolado no projeto GCP `saira-shadow-picam` (Vertex). Audit em
  `STATE_DIR/shadow_model_audit/{date}/pi-cam-001.jsonl` + `gemini_call_log agent=shadow_*`.
  Flags no `services/.env` de prod: `SHADOW_MODEL_ENABLED=true`, `SHADOW_MODEL_DEVICES=pi-cam-001`,
  `SHADOW_GCP_PROJECT=saira-shadow-picam`. Rodando desde 22/07 ~18:35 BRT.

## Objetivo do Shadow B

Medir, na pi-cam-001, **quanto o structural-delta SOZINHO** (independente do 3.1) **rejeitaria de TP
(custo de recall)** e **filtraria de FP (ganho de especificidade)** — a alavanca para atacar os 15% de
baseline-fire. É um teste puro de poder discriminante, log-only, SEM tocar na prod nem no Shadow A.

## Descobertas-chave (simplificam MUITO)

1. **structural-delta é CPU determinístico** (census-hamming 1º-vs-último frame na pile-zone, camp 41).
   **NÃO precisa de baseline treinado** (≠ BGSUB/DINOv2). Só threshold + `pile_zone_polygon` da câmera
   (pi-cam-001 já tem polígono no DB). Custo $0.
2. **O hook JÁ roda no caminho event-driven** — `detector_structural.evaluate` + `record_shadow_decision`
   estão dentro de `_process_with_gemini_cascade_window` (`main.py:980-1000`), que a pi-cam-001 usa.
   Só dispara quando `disposal=True` (= detecções que o prod 2.5 CONFIRMOU = exatamente os **TP+FP**).
   → mede "rejeitaria de TP / filtraria de FP" sem esforço. (Não vê a baseline true-neg, mas o FP-set
   dos TP+FP confirmados é o alvo certo.)
3. **Compose JÁ expõe os vars** (`docker-compose.prod.yml:293-295`): `STRUCTURAL_FILTER_MODE`,
   `STRUCTURAL_DEVICES`, `STRUCTURAL_NTILES_THR`. → **NÃO precisa de deploy/PR** — só editar o
   `services/.env` de prod + recreate do worker.
4. **Estado atual de prod (22/07)**: `STRUCTURAL_FILTER_MODE=off`, `STRUCTURAL_DEVICES=esp32_002`,
   `STRUCTURAL_NTILES_THR=2`, `STRUCTURAL_RECOVERY_MODE=off`. Tudo OFF → ligar é limpo.

## Passos do Shadow B

### 1. Calibrar o threshold offline (no dataset da campanha 47)
Adaptar os scripts da camp 41 (`benchmarks/campaigns/41-structural-delta-mangabeira-2026-06-16/scripts/`:
`census.py`, `phase_struct_signals.py`, `phase_struct_roc.py`) para o dataset `cam_picam001`:
- Para cada evento (tp/fp/baseline), computar `census_ntiles_t32` (nº de tiles 32×32 da pile-zone com
  ≥50% de pixels census-mudados entre o 1º e o último frame legível) — a mesma métrica de
  `detector_structural.evaluate`.
- Precisa da `pile_zone_polygon` da pi-cam-001 (pegar do DB: `SELECT pile_zone_polygon FROM cameras
  WHERE device_id='pi-cam-001'`, ou do handoff `tasks/handoff_picam_monitoramento.md:133-146`).
- Plotar TP vs FP vs baseline → escolher `STRUCTURAL_NTILES_THR` (regra: `should_reject = n_tiles_changed
  < threshold`; poucos tiles mudados = sem depósito). Meta: recall-safe (rejeita ~0 TP) maximizando FP
  filtrado. Reportar AUC/holdout como a camp 41 (que deu AUC 0,827 no esp32_002).
- ⚠️ O polígono pode não estar calibrado p/ o enquadramento da pi-cam-001 — validar visualmente que a
  pile-zone cobre a área de descarte real (frames em `data/datasets/official/cam_picam001/tp/*/frames/`).

### 2. Ligar em prod (log-only, SÓ .env + recreate — sem deploy)
No `services/.env` de prod (backup antes; `.env` é COMPARTILHADO test↔prod, mas structural é
device-gated → só afeta quem processa pi-cam-001 = worker de prod):
```
STRUCTURAL_FILTER_MODE=shadow
STRUCTURAL_DEVICES=pi-cam-001          # escopo só na câmera do estudo (esp32_002 estava com FILTER off)
STRUCTURAL_NTILES_THR=<tunado no passo 1>
```
Recreate: `ssh saira-prod` → `cd /home/ubuntu/saira/services && docker compose -p saira-prod --profile
worker -f docker-compose.prod.yml up -d --no-deps --force-recreate yolo-worker`.
⚠️ `STRUCTURAL_FILTER_MODE` é GLOBAL (não por-device). Como estava `off`, ligar `shadow` só adiciona
logging para os `STRUCTURAL_DEVICES`. Se quiser manter esp32_002 fora, deixe `STRUCTURAL_DEVICES=pi-cam-001`.

### 3. Verificar
- `docker exec saira-yolo-worker-prod printenv | grep STRUCTURAL` → confere shadow + pi-cam-001.
- Logs: `docker logs --since 10m saira-yolo-worker-prod | grep structural_shadow_would_reject`.
- Ledger: `STATE_DIR/structural/...` (via `record_shadow_decision`, `detector_structural.py:142`) —
  campos `n_tiles_changed, threshold, should_reject, gemini_disposal, request_id, device_id`.
- Confirmar que NÃO muda a decisão de prod (é shadow; só loga).

### 4. Comparar (após 1-2 semanas)
Juntar o ledger structural + as `detections` da pi-cam-001 (status do operador) por `request_id`/tempo:
- **% de TP (CONFIRMADO) que o structural rejeitaria** = custo de recall.
- **% de FP (REJEITADO) que o structural filtraria** = ganho de especificidade.
- Cruzar com o Shadow A (3.1) e o 2.5 atual → decidir se structural entra como pré-filtro do pipeline final.

## Arquivos / referências

- `services/yolo-worker-vm/src/worker/detector_structural.py` — `evaluate` (census_ntiles_t32),
  `record_shadow_decision` (ledger), `StructFilterResult`.
- `services/yolo-worker-vm/src/worker/main.py:980-1000` — hook structural (dentro do cascade window).
- `services/yolo-worker-vm/src/worker/config.py:427-466` — flags STRUCTURAL_*.
- `docker-compose.prod.yml:293-295` — vars já expostos.
- Camp 41 (template de calibração): `benchmarks/campaigns/41-structural-delta-mangabeira-2026-06-16/`.
- Dataset: `data/datasets/official/cam_picam001/` (manifest em `data/datasets/official/manifest.csv`).
- Memória do projeto: `project_camp47_picam001_model_migration_2026-07-22` (índice em MEMORY.md).

## Gotchas / operação

- **Prod access**: `ssh saira-prod`. DB: `docker exec saira-db-prod psql -U postgres -d saira_db`.
  Worker: `saira-yolo-worker-prod`. GitHub API bloqueada → túnel `ssh -f -N -D 1080 saira-prod` +
  `HTTPS_PROXY=socks5://127.0.0.1:1080 gh` (mas Shadow B NÃO precisa de PR — só .env + recreate).
- **`.env` compartilhado test↔prod** — structural é device-gated, então setar pi-cam-001 só afeta prod.
- **Shadow A continua rodando** — não mexer. Desligar (se preciso) = `SHADOW_MODEL_ENABLED=false` + recreate.
- **Desligar Shadow B** = `STRUCTURAL_FILTER_MODE=off` no .env + recreate.
- **Custo Shadow B = $0** (CPU). Shadow A ~$21/14d no projeto `saira-shadow-picam`.
- **Follow-up paralelo**: `compare_shadow.py` (Shadow A: 3.1 vs 2.5, estimado vs billing real) — ainda a fazer.

## Verificação final (definition of done do Shadow B)
1. Threshold calibrado com AUC/separação reportada no dataset cam_picam001.
2. `structural_shadow_would_reject` aparecendo no log de prod + ledger populando, SEM mudar decisão de prod.
3. Após 1-2 semanas: tabela recall-cost vs FP-filtrado do structural, cruzada com Shadow A e 2.5.
