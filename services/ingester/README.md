# Ingester Service

Serviço responsável por capturar frames de câmeras IP via RTSP e enviá-los para AWS S3/SQS para processamento.

## Arquitetura

```
Câmeras RTSP -> Ingester -> S3 (landing-zone) -> SQS (notificação)
```

## Estrutura

```
ingester/
├── config/
│   └── cameras.yaml       # Configuração das câmeras
├── src/ingester/
│   ├── main.py            # Entry point
│   ├── config.py          # Configurações
│   ├── cameras.py         # Loader de câmeras YAML
│   ├── s3.py              # Upload para S3
│   ├── sqs.py             # Notificações SQS
│   └── rtsp/
│       └── capture.py     # Captura RTSP com circuit breaker
├── Dockerfile
├── pyproject.toml
└── .env
```

## Configuração

### Variáveis de ambiente (.env)

```bash
# Loop Control
INGESTER_RUN_FOREVER=true
INGESTER_MAX_CYCLES=0
INGESTER_CAPTURE_INTERVAL_SECONDS=300

# AWS
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
S3_LANDING_ZONE_BUCKET=saira-landing-zone
SQS_INGESTION_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/...

# Cameras
CAMERAS_CONFIG_PATH=config/cameras.yaml

# Circuit Breaker
INGESTER_CB_FAILURE_THRESHOLD=5
INGESTER_CB_RECOVERY_TIMEOUT=300
```

### Configuração de câmeras (config/cameras.yaml)

```yaml
cameras:
  - id: camera_rpa1_001
    rpa: 1
    rtsp_url: rtsp://user:pass@192.168.1.100:554/stream1
    capture_interval_seconds: 300
    active: true

  - id: camera_rpa2_001
    rpa: 2
    rtsp_url: rtsp://user:pass@192.168.1.101:554/stream1
    capture_interval_seconds: 300
    active: true
```

## Execução

### Docker (recomendado)

```bash
docker build -t saira-ingester .
docker run --env-file .env saira-ingester
```

### Local (desenvolvimento)

```bash
# Instalar dependências
poetry install

# Executar
cd services/ingester
PYTHONPATH=src python -m ingester.main
```

## Funcionalidades

- **Captura RTSP**: Conecta às câmeras via OpenCV com transporte TCP
- **Circuit Breaker**: Desabilita temporariamente câmeras com falhas consecutivas
- **Retry com backoff**: Tentativas automáticas com exponential backoff para uploads
- **Upload S3**: Salva frames em `s3://{bucket}/raw/{camera_id}/{timestamp}.jpg`
- **Notificação SQS**: Envia mensagem com metadados para processamento downstream

## Logs

O log principal é gravado em `logs/ingester.log` com rotação automática.

```bash
# Acompanhar em tempo real
tail -f logs/ingester.log
```
