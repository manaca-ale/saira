# Campaign 47 — pi-cam-001 model migration (current vs Gemini-3 replacements)

**Por quê:** os modelos de produção `gemini-2.5-flash-lite` (gate) e `gemini-2.5-flash`
(detail) serão **desligados em 16/out/2026**. Esta campanha constrói o primeiro dataset
de benchmark para a câmera **pi-cam-001** (event-driven, Residencial Via Mangue III-2,
Imbiribeira) e compara os modelos atuais contra os substitutos recomendados pelo Google,
reproduzindo fielmente a janela de produção.

## Dataset (novo): `data/datasets/official/cam_picam001/`

| cat | eventos | origem |
|---|---|---|
| tp | 30 | detecções CONFIRMADO (por evento) |
| fp | 37 | detecções REJEITADO |
| indefinido | 15 | detecções INDETERMINADO |
| baseline | 40 | eventos sem-ocorrência (negativos verdadeiros) |

Fonte: pull read-only de `saira-db-prod` (55 detecções, 14–22/07) → `detection_frames`
+ manifests de evento do esp32-server → frames do S3 `ocorrencias/` (+ disco local p/ 22/07).
Unidade = **evento** (manifest): 1 rodada de cascade. Detecções coalescidas são divididas
por `event_ref`; o label é herdado da detecção-pai (`source_detection_id` no `label.json`).

## Fidelidade (event-driven, = `worker.main._process_event_device`)

```
window = sorted(frames) -> subsample_frames(48) -> fit_frames_to_payload(8_000_000)
gate   = analyze_new_litter_with_gemini(first=win[0], last=win[-1], mid_frames=3 mids)
trigger= new_litter_detected and confidence_0_100 >= 85
detail = analyze_with_gemini(image_paths=win)   [só se gate dispara]
prompt = V1 (GEMINI_PROMPT_VERSION=current); SEM crops/DINOv2/structural (esp32-only)
```

Checagem de fidelidade (modelos atuais, 5 eventos TP): **5/5 por detecção** reproduzem
prod (1 evento não dispara — é a cauda coalescida de outro que dispara; comportamento
correto do gate, valida o split por evento).

## Como reproduzir

```bash
# 1. pull do corpus (read-only)
cat sql/pull_picam001.sql | ssh saira-prod \
  'docker exec -i saira-db-prod psql -U postgres -d saira_db -q -f -' > .tmp/corpus_picam001.csv
# 2. copiar detection_frames (worker) + event manifests (esp32-server) p/ .tmp/df, .tmp/events
# 3. baixar frames + escrever labels
python scripts/build_picam_dataset.py --apply
# 4. baseline (sem-ocorrência)
python scripts/fetch_baseline.py            # seleciona 40; pull dos frames; depois:
python scripts/fetch_baseline.py --place
# 5. dobrar no manifest mestre
python ../../scripts/rebuild_official_manifest.py --apply
# 6. benchmark (Vertex saira-tests OU AI Studio key)
export GEMINI_TEST_API_KEY=...              # conta Saira - Testes
python scripts/bench_picam.py --arms current,repl,cheap --workers 5
```

## Braços

| braço | gate | detail |
|---|---|---|
| current | gemini-2.5-flash-lite | gemini-2.5-flash |
| repl | gemini-3.1-flash-lite | gemini-3.6-flash |
| cheap | gemini-3.1-flash-lite | gemini-3.5-flash-lite |

Resultados em `results/bench_picam_summary.json` e `report.md`.

## Auth de teste

`.env.benchmark` (Vertex ADC keyless, conta Saira-Testes) é o padrão. Como o ADC expirou
e a key registrada estava 429, esta rodada usou a AI Studio key de teste ativa via
`GEMINI_TEST_API_KEY` (`GEMINI_USE_VERTEX=false`). NUNCA usar a key/projeto de produção.
