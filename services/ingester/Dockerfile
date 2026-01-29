# Usar uma imagem base oficial do Python
FROM python:3.11-slim

# Instalar o cliente ADB do Linux
RUN apt-get update && \
    apt-get install -y android-tools-adb && \
    rm -rf /var/lib/apt/lists/*

# Definir o diretório de trabalho no container
WORKDIR /app

# Instalar Poetry
RUN pip install --no-cache-dir poetry

# Copiar o restante do código-fonte da aplicação
COPY . .

# Instalar as dependências do projeto
# O --no-interaction previne perguntas interativas
RUN poetry config virtualenvs.create false && poetry install --no-interaction

# Comando para executar a aplicação como um módulo
CMD ["python", "-m", "ingester.main"]
