# SAIRA — Stack de monitoramento de PRODUÇÃO

Adicionado em 2026-06-09 após 3 incidentes só percebidos por inspeção manual.
Até então **apenas o worker de TESTE era raspado**; o de prod rodava cego.

## O que sobe (no `docker-compose.prod.yml`, projeto `saira-prod`)

| Serviço | Container | Porta (host, só localhost) | Função |
|---|---|---|---|
| prometheus | `saira-prometheus-prod` | `127.0.0.1:9092` | raspa `yolo-worker:9108`, avalia `alert.rules.yml` |
| alertmanager | `saira-alertmanager-prod` | `127.0.0.1:9093` | roteia alertas → e-mail (Resend SMTP) |
| grafana | `saira-grafana-prod` | `127.0.0.1:3005` | dashboards (reusa provisioning + dashboards existentes) |

As portas são bind em `127.0.0.1` — acesse via SSH tunnel, ex.:
`ssh -L 9092:127.0.0.1:9092 -L 3005:127.0.0.1:3005 -L 9093:127.0.0.1:9093 saira-prod`

## Pré-requisitos no servidor (antes do 1º deploy)

1. **Segredo do Resend p/ o Alertmanager** (não vai no git):
   ```bash
   printf '%s' "$RESEND_API_KEY" > services/observability/alertmanager/secrets/resend_api_key
   ```
   (mesma key já usada pelo backend no billing). Sem isso o e-mail de alerta falha na hora do envio (mas o container sobe normal).

2. **Recriação do worker prod** — o worker passou a declarar `WORKER_METRICS_*`.
   Subir a stack recria o `saira-yolo-worker-prod`. ⚠️ **Coordene com a sessão de
   monitoramento do worker** antes do deploy de prod.

## Deploy

O deploy de prod (`.github/workflows/deploy.yml`, push na `main`) já usa
`--profile worker` e `up -d --build --force-recreate`, então a stack sobe junto.
Os 3 serviços de monitoramento **não têm profile** → sobem em todo deploy de prod.

## Alertas (em `prometheus/alert.rules.yml`)

- **GeminiGateQuotaOrAuthOutage** — `saira_gemini_error_type_total{agent="gate",error_type=~"quota|auth"}` subiu em 10min (429/créditos ou credencial/WIF). Foi o incidente de 08-09/06.
- **GeminiGateStalled** — worker processou imagens mas o gate não fez nenhuma chamada em 15min (gate_ok zerado).
- **WorkerNoScanCycles** — `saira_worker_scan_cycles_total` parado 10min.
- **WorkerMetricsDown** — `up{job="saira-yolo-worker"} == 0` (não raspa o :9108).

Validar uma regra sem esperar incidente: `amtool alert add` no alertmanager, ou
baixar `for:` p/ `0s` temporariamente. Conferir e-mail chegando via Resend.

## Câmera offline

NÃO é alerta do Prometheus — é tratado no backend (app-level), em
`app/services/offline_monitor.py`, que lê o mtime dos uploads e manda e-mail
direto (Resend). Independe desta stack (funciona mesmo se o Prometheus cair).

## Teste

A stack de TESTE (`docker-compose.test.yml`, `prometheus.test.yml`) segue como
estava (raspando o worker de teste). As `alert.rules.yml`/Alertmanager são
de prod; se quiser alertas no teste, replicar o padrão apontando p/ o worker de teste.
