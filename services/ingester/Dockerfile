# Imagem base Python
FROM python:3.11-slim

# Instalar dependências do sistema para OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1-mesa-glx \
    libsm6 \
    libxext6 \
    libxrender1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar Poetry
RUN pip install --no-cache-dir poetry

# Copiar arquivos de dependências primeiro (melhor cache)
COPY pyproject.toml poetry.lock* ./

# Instalar dependências
RUN poetry config virtualenvs.create false && poetry install --no-interaction --no-dev

# Copiar código fonte
COPY src/ ./src/
COPY config/ ./config/

# Comando para executar
CMD ["python", "-m", "ingester.main"]
