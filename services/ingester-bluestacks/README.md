# Ingester BlueStacks Mode

Este serviço é uma cópia do ingester para uso com BlueStacks, sem alterar o ingester original.

## Pré-requisitos
- Python 3.11+
- Android SDK Platform-Tools (ADB) no PATH
- BlueStacks aberto com ADB habilitado

## Configuração
Defina o serial do BlueStacks via variável de ambiente:

```powershell
$env:INGESTER_DEVICE_SERIAL="127.0.0.1:5555"
```

Se precisar listar devices:

```powershell
adb devices
```

## Execução

```powershell
cd C:\saira\services\ingester-bluestacks
poetry install
python -m ingester.main
```

## Observações
- Coordenadas de taps dependem da resolução do BlueStacks; ajuste em `src/ingester/config.py`.
- Se o serial não estiver presente em `adb devices`, o ingester não inicia captura.
