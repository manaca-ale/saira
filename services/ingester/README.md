# Ingester Service

Serviço responsável por capturar screenshots de câmeras via app Android (ICSee) usando ADB.

## Estrutura de pastas importante

- Logs: `services/ingester/logs/`
- Capturas: `services/ingester/data/captures/<camera_name>/`
- Dashboard estático: `services/ingester/src/ingester/dashboard_static/`

## Execução local (Windows/macOS)

> No Windows/macOS, execute direto no host (Docker Desktop não expõe USB bem).

**Pré-requisitos**
- Python 3.11+
- ADB (Android SDK Platform-Tools) no PATH
- Dispositivo Android conectado (`adb devices`)
- Dependências instaladas (Poetry)

**Instalar dependências**

```powershell
cd C:\saira\services\ingester
poetry install
```

**Executar ingester (modo local)**

```powershell
cd C:\saira\services\ingester
$env:PYTHONPATH = "$PWD\src"
python -m ingester.main
```

> O loop de captura grava ciclos em `logs/cycles.jsonl` e screenshots em `data/captures/<camera_name>/`.

## Dashboard

**Subir o dashboard**

```powershell
cd C:\saira\services\ingester
$env:PYTHONPATH = "$PWD\src"
python -m ingester.dashboard
```

Abra: `http://127.0.0.1:8088`

### Controles disponíveis

- **Rodar 1 ciclo**: executa um ciclo (mesmo em pausa)
- **Pausar / Retomar**: pausa/retoma o loop
- **Stop**: encerra o loop no próximo checkpoint
- **Arquivar logs**: move logs e capturas para `logs/archives/archive_<timestamp>` (somente com Stop ativo)

> O estado do controle fica em `logs/control.json`.

## Logs

- Log principal: `logs/ingester.log`
- Ciclos: `logs/cycles.jsonl`
- Health checks: `logs/health.jsonl`

Acompanhar em tempo real:

```powershell
Get-Content C:\saira\services\ingester\logs\ingester.log -Wait
```

## Configuração

- Config principal: `services/ingester/src/ingester/config.py`
- Variáveis de ambiente (opcional): `services/ingester/.env`

**Câmeras**

As câmeras são definidas em `config.py` usando o nome da câmera como pasta de captura:

```python
CAMERAS = {
    "camera_quarto_1": {"tap_coords": {"x": 833, "y": 480}},
    "camera_quarto_2": {"tap_coords": {"x": 250, "y": 480}},
}
```

## Produção / Docker (Linux)

```bash
docker compose up ingester --build
```

O container instala `adb` e dependências automaticamente.

## Troubleshooting rápido

- **Botões não fazem nada**: o ingester precisa estar rodando; os botões só alteram `control.json`.
- **404 em /api/archive**: o dashboard rodando não é o correto. Verifique `/api/version`.
- **Acentos quebrados**: faça hard refresh (Ctrl+F5) e confirme UTF-8.
