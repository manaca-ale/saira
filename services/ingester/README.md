# Ingester Service

Este serviço é responsável por capturar imagens de dispositivos.

## Modos de Execução

O Ingester foi projetado para operar em dois ambientes distintos:

### 1. Desenvolvimento Local (Windows/macOS)

Devido às limitações de acesso a dispositivos USB do Docker Desktop, o modo de desenvolvimento e teste no Windows ou macOS deve ser executado diretamente no host.

**Pré-requisitos:**
- Python 3.11+ instalado
- Android SDK Platform-Tools (ADB) instalado e adicionado ao `PATH` do sistema.
- Um dispositivo Android (físico ou emulador) conectado e visível via `adb devices`.
- Dependências Python instaladas via `poetry install`.

**Execução:**

Navegue até o diretório `services/ingester` e execute o módulo:

```powershell
# Instalar dependências (apenas na primeira vez)
poetry install

# Executar o processo de captura
python -m ingester.main
```

As capturas de tela serão salvas no diretório `services/ingester/data/captures`.

### 2. Produção / Implantação (Linux/Mini-PC)

Para implantação em um ambiente Linux (como o mini-PC alvo do projeto), o serviço é executado via Docker, garantindo um ambiente consistente e autocontido.

**Execução:**

Use o Docker Compose a partir do diretório `services`:

```bash
docker compose up ingester --build
```

O Dockerfile se encarrega de instalar o `adb` e todas as dependências necessárias dentro do container.