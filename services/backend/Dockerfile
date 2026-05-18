FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema para PostGIS + WeasyPrint (PDF do relatório diário)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Tornar script de inicialização executável
RUN chmod +x start.sh

# Expor porta
EXPOSE 8001

# Comando padrão - executa migrações e inicia o servidor
CMD ["./start.sh"]
