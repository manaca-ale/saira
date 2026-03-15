# YOLO Worker VM

Servico de deteccao de residuos por visao computacional, executado em uma instancia EC2 dedicada. Consome mensagens de uma fila SQS, processa imagens com o modelo YOLO e persiste os resultados no banco de dados.

## Stack

- **YOLO** (deteccao de objetos)
- **AWS SQS** (fila de mensagens)
- **AWS S3** (armazenamento de imagens)
- **PostgreSQL** (persistencia de deteccoes)

## Estrutura

```text
src/worker/
├── main.py              # Entry point - loop de consumo da fila SQS
├── config.py            # Configuracoes (credenciais, URLs, thresholds)
├── detector_yolo.py     # Inferencia do modelo YOLO sobre imagens
├── models.py            # Modelos de dados internos
├── queue_sqs.py         # Consumo e acknowledge de mensagens SQS
├── storage_s3.py        # Download/upload de imagens no S3
└── db.py                # Conexao e insercao de deteccoes no PostgreSQL
```

## Fluxo

1. Camera captura frame e envia mensagem para fila SQS
2. Worker consome a mensagem, faz download da imagem do S3
3. Modelo YOLO processa a imagem e identifica residuos
4. Resultado (tipo, volume estimado, confianca) e salvo no banco
5. Imagem anotada e reenviada ao S3

## Deploy

O worker roda como servico systemd em uma EC2:

```bash
# Arquivo de servico
systemd/saira-yolo-worker.service
```

### Download dos pesos do modelo

```bash
./scripts/download_weights.sh
```

Consulte o runbook em `docs/runbooks/yolo-vm.md` para instrucoes detalhadas de provisionamento e operacao.
