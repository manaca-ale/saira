# Worker de IA (YOLO + Gemini)

Worker responsavel por processar imagens em `UPLOAD_DIR`, identificar ocorrencias de descarte irregular e persistir resultados no PostgreSQL.

## Modos de execucao

- `AI_MODE=yolo`: fluxo legado YOLO.
- `AI_MODE=shadow`: YOLO persiste ocorrencias e Gemini roda em paralelo para auditoria/custos.
- `AI_MODE=gemini`: Gemini persiste ocorrencias (sem edge computing).

## Stack principal

- Python 3.11
- OpenCV + YOLO (modos `yolo` e `shadow`)
- Gemini Developer API (modos `shadow` e `gemini`)
- PostgreSQL + Redis

## Estrutura

```text
src/worker/
├── main.py              # Loop principal com AI_MODE yolo|shadow|gemini
├── config.py            # Variaveis de ambiente
├── detector_yolo.py     # Inferencia YOLO
├── detector_mock.py     # Inferencia mock
├── detector_gemini.py   # Cliente Gemini + retries + structured output
├── schemas_gemini.py    # Contrato Pydantic da resposta Gemini
├── models.py            # Dataclasses internas
├── db.py                # Persistencia em detections e detection_offenders
└── gdrive_sync.py       # Sync opcional para Google Drive
```

## Variaveis importantes

- `AI_MODE` (`yolo|shadow|gemini`)
- `GEMINI_API_KEY` (obrigatoria em `shadow` e `gemini`)
- `GEMINI_MODEL` (default `gemini-2.5-flash`)
- `GEMINI_SEQUENCE_SIZE` e `GEMINI_SEQUENCE_MAX_SPAN_SECONDS`
- `GEMINI_DRY_RUN` (chama Gemini sem persistir)
- `WORKER_ENABLED`

## Auditoria Shadow

No modo `shadow`, o worker grava:

- JSONL por dispositivo/dia em `STATE_DIR/shadow_audit/<YYYY-MM-DD>/<device_id>.jsonl`
- metricas diarias agregadas em `STATE_DIR/shadow_audit/<YYYY-MM-DD>/metrics.json`

## Execucao local

```bash
docker compose --profile worker up -d --build
docker compose logs -f yolo-worker
```

## Observacao

Nao versionar chave real em `.env`.
