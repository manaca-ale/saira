FROM python:3.11-slim

WORKDIR /app

# OpenCV headless deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libxcb1 \
        libx11-6 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY models/ ./models/

WORKDIR /app/src

CMD ["python", "-m", "worker.main"]
