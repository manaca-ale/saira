    # SPEC de Implementacao — Pipeline de Dados SAIRA

> Referencia: `PLANO_FINALIZACAO_PIPELINE.md` v3
> Objetivo: Especificacao detalhada para implementacao autonoma por agente
> Cada tarefa inclui: arquivos a modificar, codigo esperado, criterios de aceite e testes

---

## Convencoes

- **Backend** usa SQLAlchemy 2.0 async com asyncpg. Sessions via `get_db()` em `app/core/database.py`.
- **Migrations** via Alembic async (`alembic/env.py`). Apenas 1 migration existente: `9820af489db3_initial_migration`.
- **Detection POST** existente: `POST /api/v1/detections` (requer auth). Schema: `DetectionCreate`.
- **Worker stubs**: Todos os arquivos em `services/yolo-worker-vm/src/worker/` estao vazios.
- **Firmware**: PlatformIO, ESP32-S3 DevKitC-1 N16R8 (8MB PSRAM), ambiente `ipcam-relay-esp32s3-devkitc-1-n16r8`, porta COM20. Macros via `saira_config.h`.
- **Cleanup script existente**: `services/scripts/backup_uploads_if_low_space.sh` (rclone para Google Drive).

---

## TAREFA 1: Firmware — Header X-Device-Id no upload

**Prioridade:** CRITICA
**Arquivos a modificar:** `firmware/espcam-saira/src/ipcam_relay.cpp`
**Esforco:** Pequeno (~5 linhas)

### O que fazer

Na funcao `uploadSnapshot()`, adicionar o header `X-Device-Id` com o valor da macro `SAIRA_DEVICE_ID` (ja definida em `saira_config.h` linha 62-64, default `"esp32"`).

### Localizacao exata

Arquivo: `firmware/espcam-saira/src/ipcam_relay.cpp`
Funcao: `uploadSnapshot()` (linha 465)

Inserir **uma linha** entre a linha do `Content-Length` (linha 515) e o `\r\n` final dos headers (linha 516):

```cpp
// ANTES (linhas 514-516):
  sock->print(String("Content-Type: multipart/form-data; boundary=") + boundary + "\r\n");
  sock->print(String("Content-Length: ") + String(totalLen) + "\r\n");
  sock->print("\r\n");

// DEPOIS:
  sock->print(String("Content-Type: multipart/form-data; boundary=") + boundary + "\r\n");
  sock->print(String("Content-Length: ") + String(totalLen) + "\r\n");
  sock->print(String("X-Device-Id: ") + String(SAIRA_DEVICE_ID) + "\r\n");
  sock->print("\r\n");
```

### Criterios de aceite

1. Header `X-Device-Id` presente em todo POST /upload
2. Valor vem de `SAIRA_DEVICE_ID` (macro, configuravel por device via `.env`)
3. Firmware compila sem erros

### Teste

```bash
cd firmware/espcam-saira
pio run --environment ipcam-relay-esp32s3-devkitc-1-n16r8
# Deve compilar sem erros
# Verificar no output que X-Device-Id aparece no codigo objeto
```

Flash e teste funcional:

```bash
pio run --target upload --environment ipcam-relay-esp32s3-devkitc-1-n16r8
pio device monitor --port COM20 --baud 115200
```

- Observar logs do esp32-server: o header deve aparecer no request
- Imagem deve ser salva no subdir do device_id (apos Tarefa 3)

---

## TAREFA 2: Firmware — Fila PSRAM (captura desacoplada do upload)

**Prioridade:** CRITICA
**Arquivos a modificar:** `firmware/espcam-saira/src/ipcam_relay.cpp`
**Esforco:** Medio

### O que fazer

Substituir o ciclo sequencial (download + upload bloqueante) por uma fila circular na PSRAM que desacopla captura de upload. A captura acontece em intervalo fixo; o upload drena a fila quando possivel.

### Estrutura de dados (adicionar antes da funcao `setup()`)

```cpp
// ---- Fila de imagens na PSRAM ----
static const int IMAGE_QUEUE_MAX = 20;

struct QueuedImage {
    uint8_t* data;       // ponteiro PSRAM (ps_malloc)
    int      length;     // tamanho JPEG em bytes
    uint32_t capturedAt; // millis() da captura
};

static QueuedImage imageQueue[IMAGE_QUEUE_MAX];
static int queueHead = 0;  // proximo slot a ser consumido (upload)
static int queueTail = 0;  // proximo slot a ser escrito (captura)
static int queueCount = 0;

static bool queuePush(uint8_t* data, int len, uint32_t ts) {
    if (queueCount >= IMAGE_QUEUE_MAX) {
        // Fila cheia: descarta imagem mais antiga
        free(imageQueue[queueHead].data);
        queueHead = (queueHead + 1) % IMAGE_QUEUE_MAX;
        queueCount--;
        Serial.println("QUEUE: descartou imagem mais antiga (fila cheia)");
    }
    imageQueue[queueTail].data = data;
    imageQueue[queueTail].length = len;
    imageQueue[queueTail].capturedAt = ts;
    queueTail = (queueTail + 1) % IMAGE_QUEUE_MAX;
    queueCount++;
    Serial.printf("QUEUE: enfileirou (%d bytes), total na fila: %d\n", len, queueCount);
    return true;
}

static bool queuePop(QueuedImage& out) {
    if (queueCount <= 0) return false;
    out = imageQueue[queueHead];
    imageQueue[queueHead] = {nullptr, 0, 0};
    queueHead = (queueHead + 1) % IMAGE_QUEUE_MAX;
    queueCount--;
    return true;
}
```

### Nova logica do `loop()` (substituir o bloco existente das linhas 583-630)

```cpp
static uint32_t nextCaptureAt = 0;
static bool uploading = false;

void loop() {
  sairaMaybeCheckOta();

  // Remote config (manter logica existente das linhas 588-621)
  auto applyFn = +[](const String& key, const String& value) -> bool {
    bool changed = false;
    String k = key; k.toLowerCase();
    if (k == "timer_delay_ms") {
      long v = value.toInt();
      if (v >= 1000 && (uint32_t)v != timerDelayMs) {
        timerDelayMs = (uint32_t)v;
        changed = true;
      }
    } else if (k == "ip_cam_url") {
      if (value.length() && value != ipCamUrl) { ipCamUrl = value; changed = true; }
    } else if (k == "ip_cam_user") {
      if (value != ipCamUser) { ipCamUser = value; changed = true; }
    } else if (k == "ip_cam_pass") {
      if (value != ipCamPass) { ipCamPass = value; changed = true; }
    }
    if (changed) Serial.println("CFG: aplicado (ipcam-relay).");
    return changed;
  };
  (void)sairaMaybeFetchRemoteConfig(String(SERVER_BASE), applyFn);

  // 1. CAPTURA em intervalo fixo
  if (nextCaptureAt == 0) nextCaptureAt = millis();
  if ((int32_t)(millis() - nextCaptureAt) >= 0) {
    // IMPORTANTE: avancar timer ANTES do download para manter intervalo fixo
    nextCaptureAt += timerDelayMs;

    // Evitar acumulo se ficou muito tempo sem rodar
    if ((int32_t)(millis() - nextCaptureAt) >= (int32_t)timerDelayMs) {
      nextCaptureAt = millis() + timerDelayMs;
    }

    if (ensureWiFi()) {
      uint8_t* buf = nullptr;
      int len = 0;
      Serial.println("\n--- CAPTURA ---");
      if (downloadSnapshot(buf, len)) {
        Serial.printf("   OK: %d bytes capturados\n", len);
        queuePush(buf, len, millis());
        // NAO fazer free(buf) aqui — a fila agora eh dona do ponteiro
      } else {
        Serial.println("   ERRO: falha na captura");
      }
    }
  }

  // 2. UPLOAD: drena fila (um por iteracao do loop para nao bloquear captura por muito tempo)
  if (queueCount > 0 && ensureWiFi()) {
    QueuedImage img;
    if (queuePop(img)) {
      Serial.printf("\n--- UPLOAD (fila restante: %d) ---\n", queueCount);
      uploadSnapshot(img.data, img.length);
      free(img.data);
    }
  }
}
```

### Remover

- Variavel global `nextRunAt` (linha 39) — substituida por `nextCaptureAt`
- Funcao `relayExternalImage()` (linhas 541-566) — logica absorvida pelo loop
- Referencia a `nextRunAt` no `applyFn` do remote config (linha 617)

### Criterios de aceite

1. Captura acontece a cada `timerDelayMs` independente do tempo de upload
2. Se upload demora mais que `timerDelayMs`, imagens acumulam na fila
3. Se fila cheia (20 imagens), descarta a mais antiga
4. Memoria PSRAM usada (ps_malloc no downloadSnapshot ja existe — linha 388)
5. Timer usa adicao (`nextCaptureAt += timerDelayMs`) para nao acumular drift
6. Firmware compila sem erros

### Teste

```bash
cd firmware/espcam-saira
pio run --environment ipcam-relay-esp32s3-devkitc-1-n16r8
# Deve compilar sem erros
```

Flash e teste funcional:

```bash
pio run --target upload --environment ipcam-relay-esp32s3-devkitc-1-n16r8
pio device monitor --port COM20 --baud 115200
```

- Configurar `timerDelayMs = 10000` (10s)
- Observar Serial: capturas a cada ~10s, uploads intercalados
- Se upload demora >10s, devem aparecer mensagens "QUEUE: enfileirou, total na fila: 2+"

---

## TAREFA 3: esp32-server — Organizar uploads por device_id

**Prioridade:** CRITICA
**Arquivos a modificar:** `esp32-server/server.py`
**Esforco:** Pequeno

### O que fazer

Modificar o endpoint `POST /upload` para:
1. Ler header `X-Device-Id`
2. Organizar path como `uploads/{device_id}/YYYY/MM/DD/HH-MM-SS.jpg`
3. Retornar `device_id` no JSON de resposta
4. Fallback para `unknown_device` se header ausente

### Codigo (substituir funcao `upload_file` — linhas 254-299)

```python
@app.route("/upload", methods=["POST"])
def upload_file():
    # Identify the device
    raw_device_id = request.headers.get("X-Device-Id", "").strip()
    device_id = _sanitize_device_id(raw_device_id) if raw_device_id else None
    if not device_id:
        device_id = "unknown_device"
        if raw_device_id:
            print(f"WARNING: X-Device-Id invalido: {raw_device_id!r}", flush=True)
        else:
            print("WARNING: upload sem header X-Device-Id, usando fallback", flush=True)

    # Validate that an image file was provided
    if "imageFile" not in request.files:
        print(
            "Upload missing imageFile | "
            f"device_id={device_id} | "
            f"content_type={request.content_type} | "
            f"content_length={request.headers.get('Content-Length')} | "
            f"files_keys={list(request.files.keys())} | "
            f"form_keys={list(request.form.keys())} | "
            f"data_len={len(request.get_data() or b'')}",
            flush=True,
        )
        return {"error": "Missing imageFile"}, 400

    file = request.files["imageFile"]
    if file.filename == "":
        print(
            "Upload empty filename | "
            f"device_id={device_id} | "
            f"content_type={request.content_type} | "
            f"content_length={request.headers.get('Content-Length')} | "
            f"files_keys={list(request.files.keys())}",
            flush=True,
        )
        return {"error": "Empty filename"}, 400

    # Build path: {device_id}/YYYY/MM/DD/HH-MM-SS.jpg
    dt = datetime.utcnow()
    timestamp_str = dt.strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp_str}.jpg"
    rel_path = os.path.join(device_id, dt.strftime("%Y/%m/%d"), filename)
    save_path = os.path.join(UPLOAD_ROOT, rel_path)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)

    print(f"Received image: {rel_path} (device={device_id})", flush=True)

    base = _public_base_url()
    rel_url = rel_path.replace(os.sep, "/")
    if base:
        image_url = f"{base}/uploads/{rel_url}"
    else:
        image_url = f"/uploads/{rel_url}"

    return {
        "status": "ok",
        "device_id": device_id,
        "filename": rel_url,
        "image_url": image_url,
    }, 200
```

### Criterios de aceite

1. Imagens com `X-Device-Id: cam_01` salvas em `uploads/cam_01/2026/02/08/...`
2. Imagens sem header salvas em `uploads/unknown_device/2026/02/08/...`
3. Device IDs maliciosos (path traversal) rejeitados pelo `_sanitize_device_id` existente
4. JSON de resposta inclui `device_id` e `image_url` com path completo
5. Imagens servidas via `GET /uploads/{device_id}/...` (ja funciona pelo handler existente)

### Teste

```bash
# Teste com device_id
curl -X POST http://localhost:5001/upload \
  -H "X-Device-Id: test_cam_01" \
  -F "imageFile=@test_image.jpg"
# Esperado: {"status":"ok","device_id":"test_cam_01","filename":"test_cam_01/2026/02/08/...","image_url":"..."}

# Teste sem device_id
curl -X POST http://localhost:5001/upload \
  -F "imageFile=@test_image.jpg"
# Esperado: {"status":"ok","device_id":"unknown_device",...}

# Teste com device_id invalido (path traversal)
curl -X POST http://localhost:5001/upload \
  -H "X-Device-Id: ../../../etc" \
  -F "imageFile=@test_image.jpg"
# Esperado: device_id = "unknown_device" (sanitize rejeita)

# Verificar que o arquivo existe no path correto
ls esp32-server/uploads/test_cam_01/
# Deve ter subdiretorio YYYY/MM/DD/ com a imagem
```

Criar imagem de teste para os curls:

```bash
# Criar uma imagem JPEG minima para testes (1x1 pixel)
python -c "
from PIL import Image
img = Image.new('RGB', (1, 1), color='red')
img.save('test_image.jpg')
" 2>/dev/null || python -c "
import struct, sys
# Minimal valid JPEG (1x1 red pixel)
data = bytes.fromhex('ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc40000ffd9')
sys.stdout.buffer.write(data)
" > test_image.jpg
```

---

## TAREFA 4: Backend — Migration device_id na tabela cameras

**Prioridade:** CRITICA
**Arquivos a modificar:**
- `services/backend/app/models/camera.py` (modelo)
- `services/backend/app/schemas/camera.py` (schema)
- Nova migration via `alembic revision --autogenerate`

**Esforco:** Pequeno

### 4a. Atualizar modelo Camera

**Arquivo:** `services/backend/app/models/camera.py`

Adicionar campo `device_id` apos `name`:

```python
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric
from datetime import datetime
from geoalchemy2 import Geometry
from app.core.database import Base


class Camera(Base):
    __tablename__ = "cameras"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    device_id = Column(String(64), unique=True, index=True, nullable=True)
    logradouro = Column(String(255))
    bairro = Column(String(100))
    rpa = Column(String(10), index=True)
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    geom = Column(Geometry("POINT", srid=4326))
    rtsp_url = Column(String(512))
    capture_interval_seconds = Column(Integer, default=30)
    is_active = Column(Boolean, default=True, index=True)
    last_capture_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 4b. Atualizar schemas Camera

**Arquivo:** `services/backend/app/schemas/camera.py`

Adicionar `device_id` aos schemas (ler o arquivo antes para ver a estrutura exata e adicionar o campo):

- `CameraBase`: `device_id: Optional[str] = Field(None, max_length=64)`
- `CameraCreate`: herda de CameraBase (nada a mudar)
- `CameraUpdate`: `device_id: Optional[str] = Field(None, max_length=64)`
- `CameraResponse`: herda de CameraBase (nada a mudar)

### 4c. Gerar migration Alembic

```bash
cd services/backend
# Ativar venv se necessario
alembic revision --autogenerate -m "add device_id to cameras"
```

Verificar a migration gerada — deve conter:
```python
def upgrade():
    op.add_column('cameras', sa.Column('device_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_cameras_device_id'), 'cameras', ['device_id'], unique=True)

def downgrade():
    op.drop_index(op.f('ix_cameras_device_id'), table_name='cameras')
    op.drop_column('cameras', 'device_id')
```

### 4d. Aplicar migration

```bash
cd services/backend
alembic upgrade head
```

### Criterios de aceite

1. Campo `device_id` (String 64, unique, nullable, indexed) existe na tabela `cameras`
2. Migration gerada e aplicavel
3. API `POST /api/v1/cameras` aceita `device_id` no body
4. API `GET /api/v1/cameras` retorna `device_id` na resposta
5. Backend inicia sem erros

### Teste

```bash
cd services/backend

# Verificar que a migration foi gerada
ls alembic/versions/
# Deve ter 2 arquivos: a initial + a nova

# Aplicar migration (requer DB rodando)
alembic upgrade head

# Testar via API (requer backend rodando)
# Criar camera com device_id
curl -X POST http://localhost:8001/api/v1/cameras \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name": "Camera Teste", "device_id": "test_cam_01", "latitude": -8.063, "longitude": -34.871}'
# Esperado: 201 com device_id no response

# Listar cameras
curl http://localhost:8001/api/v1/cameras \
  -H "Authorization: Bearer $TOKEN"
# Esperado: device_id presente em cada camera
```

---

## TAREFA 5: Fake Worker — Implementacao completa

**Prioridade:** ALTA
**Arquivos a criar/modificar:**
- `services/yolo-worker-vm/src/worker/config.py`
- `services/yolo-worker-vm/src/worker/db.py`
- `services/yolo-worker-vm/src/worker/main.py`
- `services/yolo-worker-vm/src/worker/models.py`
- `services/yolo-worker-vm/requirements.txt` (criar)
- `services/yolo-worker-vm/Dockerfile` (criar)

**Esforco:** Medio

### Importante

O fake worker roda como processo standalone (nao depende do backend FastAPI). Ele conecta direto ao PostgreSQL via psycopg2 (sync, simples). NAO usar asyncpg/SQLAlchemy async — o worker e um script simples de polling.

### 5a. `config.py`

```python
"""Configuration for the YOLO worker (fake or real)."""
import os

# Directory where esp32-server saves uploaded images.
# Must match the UPLOAD_DIR / volume mount of esp32-server.
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")

# PostgreSQL connection string (sync — psycopg2).
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/saira_db",
)

# Base URL of the esp32-server (used to build image_url for the frontend).
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:5001")

# How often to scan the uploads directory for new images (seconds).
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# When true, generate fake detections instead of running YOLO.
FAKE_MODE = os.getenv("FAKE_MODE", "true").lower() == "true"

# Processed images marker strategy: "marker" (create .processed file) or "move" (move to processed/ subdir)
PROCESSED_STRATEGY = os.getenv("PROCESSED_STRATEGY", "marker")
```

### 5b. `models.py`

```python
"""Internal data models for the worker."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4


@dataclass
class CameraInfo:
    """Camera record from the database."""
    id: int
    name: str
    device_id: Optional[str]
    logradouro: Optional[str]
    bairro: Optional[str]
    rpa: Optional[str]
    latitude: Optional[Decimal]
    longitude: Optional[Decimal]


@dataclass
class DetectionRecord:
    """A detection to be inserted into the database."""
    id: UUID = field(default_factory=uuid4)
    camera_id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    logradouro: Optional[str] = None
    bairro: Optional[str] = None
    rpa: Optional[str] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    waste_type: Optional[str] = None
    material_type: Optional[str] = None
    volume_m3: Optional[Decimal] = None
    offenders: Optional[str] = None
    status: str = "Pendente"
    image_url: Optional[str] = None
    confidence_score: Optional[Decimal] = None
```

### 5c. `db.py`

```python
"""Database operations for the worker (sync psycopg2)."""
import psycopg2
import psycopg2.extras
from typing import Optional
import logging

from . import config
from .models import CameraInfo, DetectionRecord

logger = logging.getLogger(__name__)

# Register UUID adapter for psycopg2
psycopg2.extras.register_uuid()


def get_connection():
    """Create a new database connection."""
    return psycopg2.connect(config.DATABASE_URL)


def resolve_camera(device_id: str) -> Optional[CameraInfo]:
    """Lookup camera by device_id. Returns None if not found."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, device_id, logradouro, bairro, rpa, latitude, longitude "
            "FROM cameras WHERE device_id = %s AND is_active = true LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return CameraInfo(
            id=row[0],
            name=row[1],
            device_id=row[2],
            logradouro=row[3],
            bairro=row[4],
            rpa=row[5],
            latitude=row[6],
            longitude=row[7],
        )
    except Exception:
        logger.exception("Error resolving camera for device_id=%s", device_id)
        return None


def insert_detection(det: DetectionRecord) -> bool:
    """Insert a detection record. Returns True on success."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO detections (
                id, camera_id, timestamp, logradouro, bairro, rpa,
                latitude, longitude, waste_type, material_type,
                volume_m3, offenders, status, image_url, confidence_score,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                NOW(), NOW()
            )
            """,
            (
                det.id, det.camera_id, det.timestamp,
                det.logradouro, det.bairro, det.rpa,
                det.latitude, det.longitude,
                det.waste_type, det.material_type,
                det.volume_m3, det.offenders,
                det.status, det.image_url, det.confidence_score,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Inserted detection %s (camera=%s)", det.id, det.camera_id)
        return True
    except Exception:
        logger.exception("Error inserting detection")
        return False
```

### 5d. `main.py`

```python
"""Fake YOLO worker — polls uploads directory and creates detections in the database."""
import logging
import os
import random
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from . import config
from .db import resolve_camera, insert_detection
from .models import DetectionRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

# Waste types matching frontend Detections.tsx options
WASTE_TYPES = ["Entulho", "Lixo domiciliar", "Poda", "Plastico"]
MATERIAL_TYPES = ["Concreto", "Madeira", "Metal", "Organico", "Misto"]
OFFENDER_OPTIONS = [
    None, None, None, None, None, None, None,  # 70% chance no offender
    "Veiculo identificado",
    "Pessoa flagrada",
    "Empresa identificada",
]


def is_processed(image_path: Path) -> bool:
    """Check if an image has already been processed."""
    if config.PROCESSED_STRATEGY == "marker":
        return image_path.with_suffix(".jpg.processed").exists()
    else:
        # "move" strategy: if it's in processed/ subdir, it was processed
        return "processed" in image_path.parts


def mark_processed(image_path: Path) -> None:
    """Mark an image as processed."""
    if config.PROCESSED_STRATEGY == "marker":
        marker = image_path.with_suffix(".jpg.processed")
        marker.touch()
    else:
        processed_dir = image_path.parent / "processed"
        processed_dir.mkdir(exist_ok=True)
        image_path.rename(processed_dir / image_path.name)


def parse_timestamp_from_filename(filename: str) -> datetime:
    """Extract timestamp from filename like '2026-02-08_14-30-00.jpg'."""
    name = filename.replace(".jpg", "")
    try:
        return datetime.strptime(name, "%Y-%m-%d_%H-%M-%S")
    except ValueError:
        return datetime.utcnow()


def build_image_url(device_id: str, rel_path: str) -> str:
    """Build the public URL for an image."""
    base = config.PUBLIC_BASE_URL.rstrip("/")
    clean_path = rel_path.replace("\\", "/")
    return f"{base}/uploads/{clean_path}"


def generate_fake_detection(camera, image_path: Path, device_id: str) -> DetectionRecord:
    """Generate a fake detection with random AI fields."""
    # Extract relative path from UPLOAD_DIR for image_url
    try:
        rel_path = str(image_path.relative_to(config.UPLOAD_DIR))
    except ValueError:
        rel_path = f"{device_id}/{image_path.name}"

    return DetectionRecord(
        id=uuid4(),
        camera_id=camera.id,
        timestamp=parse_timestamp_from_filename(image_path.name),
        logradouro=camera.logradouro,
        bairro=camera.bairro,
        rpa=camera.rpa,
        latitude=camera.latitude,
        longitude=camera.longitude,
        waste_type=random.choice(WASTE_TYPES),
        material_type=random.choice(MATERIAL_TYPES),
        volume_m3=Decimal(str(round(random.uniform(0.1, 50.0), 2))),
        offenders=random.choice(OFFENDER_OPTIONS),
        status="Pendente",
        image_url=build_image_url(device_id, rel_path),
        confidence_score=Decimal(str(round(random.uniform(0.50, 0.99), 2))),
    )


def scan_and_process() -> int:
    """Scan upload directory for new images and process them. Returns count of processed images."""
    upload_dir = Path(config.UPLOAD_DIR)
    if not upload_dir.exists():
        logger.warning("Upload directory does not exist: %s", upload_dir)
        return 0

    count = 0
    for device_dir in sorted(upload_dir.iterdir()):
        if not device_dir.is_dir():
            continue
        device_id = device_dir.name
        if device_id in ("processed", "unknown_device"):
            continue

        camera = resolve_camera(device_id)
        if not camera:
            logger.debug("No camera found for device_id=%s, skipping", device_id)
            continue

        for jpg in sorted(device_dir.rglob("*.jpg")):
            if is_processed(jpg):
                continue

            if config.FAKE_MODE:
                detection = generate_fake_detection(camera, jpg, device_id)
            else:
                # TODO: Replace with real YOLO inference
                logger.warning("FAKE_MODE=false but real inference not implemented")
                continue

            if insert_detection(detection):
                mark_processed(jpg)
                count += 1
                logger.info(
                    "Processed: %s -> detection %s (%s, %.2f m3)",
                    jpg.name, detection.id, detection.waste_type, detection.volume_m3,
                )

    return count


def main():
    """Main entry point — polling loop."""
    logger.info("=" * 60)
    logger.info("SAIRA Worker starting (FAKE_MODE=%s)", config.FAKE_MODE)
    logger.info("UPLOAD_DIR=%s", config.UPLOAD_DIR)
    logger.info("DATABASE_URL=%s", config.DATABASE_URL.split("@")[-1])  # hide credentials
    logger.info("PUBLIC_BASE_URL=%s", config.PUBLIC_BASE_URL)
    logger.info("POLL_INTERVAL=%ds", config.POLL_INTERVAL)
    logger.info("=" * 60)

    while True:
        try:
            processed = scan_and_process()
            if processed:
                logger.info("Cycle complete: %d images processed", processed)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception:
            logger.exception("Error in scan cycle")

        time.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    main()
```

### 5e. `__init__.py`

```python
```

(Manter vazio — ja existe.)

### 5f. `requirements.txt`

**Arquivo:** `services/yolo-worker-vm/requirements.txt`

```
psycopg2-binary==2.9.9
```

### 5g. `Dockerfile`

**Arquivo:** `services/yolo-worker-vm/Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

CMD ["python", "-m", "worker.main"]
```

### 5h. Entrada no docker-compose do esp32-server

Adicionar ao `esp32-server/docker-compose.yml` (ou criar `esp32-server/docker-compose.prod.yml` entry):

```yaml
  fake-worker:
    build:
      context: ../services/yolo-worker-vm
      dockerfile: Dockerfile
    environment:
      - UPLOAD_DIR=/app/uploads
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/saira_db
      - PUBLIC_BASE_URL=${PUBLIC_BASE_URL:-http://localhost:5001}
      - POLL_INTERVAL=10
      - FAKE_MODE=true
      - PROCESSED_STRATEGY=marker
    volumes:
      - ./uploads:/app/uploads
    depends_on:
      - esp32-receiver
    restart: unless-stopped
```

**Nota:** O worker precisa acessar tanto o volume de uploads (do esp32-server) quanto o banco de dados (do services/docker-compose). A configuracao exata de rede depende do deploy. Em producao na EC2, ambos rodam no mesmo host — basta apontar `DATABASE_URL` para `localhost`.

### Criterios de aceite

1. Worker inicia sem erros com `python -m worker.main`
2. Detecta novas imagens em `uploads/{device_id}/...`
3. Faz lookup da camera por `device_id` no banco
4. Insere detection com todos os campos que o frontend espera
5. `image_url` aponta para a imagem real no esp32-server
6. Marca imagem como processada (`.processed` marker)
7. Nao reprocessa imagens ja marcadas
8. Ignora `unknown_device/` e diretorios sem camera cadastrada
9. Logs claros no stdout

### Teste

```bash
cd services/yolo-worker-vm

# Instalar dependencias
pip install -r requirements.txt

# Preparar ambiente de teste
export UPLOAD_DIR="../../esp32-server/uploads"
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/saira_db"
export PUBLIC_BASE_URL="http://localhost:5001"
export POLL_INTERVAL=5
export FAKE_MODE=true

# Prerequisito: ter camera cadastrada no banco com device_id
# (usar API ou SQL direto):
# INSERT INTO cameras (name, device_id, latitude, longitude, logradouro, bairro, rpa, is_active)
# VALUES ('Camera Teste', 'test_cam_01', -8.063170, -34.871140, 'Rua do Apolo', 'Recife Antigo', 'RPA 1', true);

# Criar diretorio e imagem de teste simulando o esp32-server
mkdir -p "$UPLOAD_DIR/test_cam_01/2026/02/08"
cp test_image.jpg "$UPLOAD_DIR/test_cam_01/2026/02/08/2026-02-08_14-30-00.jpg"

# Rodar worker
python -m worker.main

# Esperado no log:
# - "Processed: 2026-02-08_14-30-00.jpg -> detection UUID (Entulho, 12.50 m3)"
# - Arquivo .processed criado ao lado da imagem

# Verificar no banco:
# SELECT id, camera_id, waste_type, volume_m3, image_url, status FROM detections ORDER BY created_at DESC LIMIT 1;
# Esperado: detection com image_url = http://localhost:5001/uploads/test_cam_01/2026/02/08/2026-02-08_14-30-00.jpg

# Verificar no frontend:
# Abrir http://localhost:3000 -> Deteccoes -> deve aparecer a nova deteccao com foto
```

---

## TAREFA 6: Evoluir script de limpeza de disco

**Prioridade:** ALTA
**Arquivos a modificar:** `services/scripts/backup_uploads_if_low_space.sh`
**Esforco:** Medio

### O que fazer

Evoluir o script existente adicionando:
1. Flag `ENABLE_DRIVE_BACKUP` (default `false`)
2. `UPLOAD_DIR` via env var (nao hardcoded)
3. Limpar apenas imagens processadas (com marker `.processed`)
4. Fallback: se rclone falha, ainda limpar processadas
5. Log de espaco em disco

### Codigo completo (substituir o script inteiro)

```bash
#!/usr/bin/env bash
set -euo pipefail

# ---- Configuration (env vars with defaults) ----
UPLOAD_DIR="${UPLOAD_DIR:-/home/ubuntu/saira/esp32-server/uploads}"
MIN_FREE_PERCENT="${MIN_FREE_PERCENT:-30}"
ENABLE_DRIVE_BACKUP="${ENABLE_DRIVE_BACKUP:-false}"
DRIVE_REMOTE="${DRIVE_REMOTE:-gdrive}"
DRIVE_FOLDER_ID="${DRIVE_FOLDER_ID:-1sds3yeef0o9j902X2taxFoEE0iU42sF4}"
LOG_FILE="${LOG_FILE:-/home/ubuntu/saira/esp32-server/backup_uploads.log}"
LOG_MAX_BYTES=$((10 * 1024 * 1024))
BW_LIMIT="${BW_LIMIT:-5M}"
NICE_LEVEL=10
IONICE_CLASS=2
IONICE_LEVEL=7

log() {
  echo "$(date -Is) $*" | tee -a "$LOG_FILE"
}

# ---- Log rotation ----
if [ -f "$LOG_FILE" ]; then
  LOG_SIZE=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
  if [ "$LOG_SIZE" -gt "$LOG_MAX_BYTES" ]; then
    mv "$LOG_FILE" "${LOG_FILE}.$(date -u +%Y%m%dT%H%M%SZ)"
  fi
fi

# ---- Validate ----
if [ ! -d "$UPLOAD_DIR" ]; then
  log "ERROR: upload dir not found: $UPLOAD_DIR"
  exit 1
fi

# ---- Disk space check ----
USED_PCT=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
FREE_PCT=$((100 - USED_PCT))
log "INFO: disk free ${FREE_PCT}% (threshold: ${MIN_FREE_PERCENT}%)"

if [ "$FREE_PCT" -ge "$MIN_FREE_PERCENT" ]; then
  # Even with enough space, clean up processed images older than 1 hour
  CLEANED=$(find "$UPLOAD_DIR" -name "*.processed" -mmin +60 | wc -l)
  if [ "$CLEANED" -gt 0 ]; then
    find "$UPLOAD_DIR" -name "*.processed" -mmin +60 -exec rm -f {} \;
    # Also delete the corresponding .jpg files
    find "$UPLOAD_DIR" -name "*.processed" -mmin +60 | while read -r marker; do
      jpg="${marker%.processed}"
      [ -f "$jpg" ] && rm -f "$jpg"
    done
    log "INFO: cleaned $CLEANED old processed images (disk OK)"
  fi
  log "OK: free ${FREE_PCT}% >= ${MIN_FREE_PERCENT}%, routine cleanup done."
  exit 0
fi

# ---- Disk is getting full — clean processed images ----
log "WARNING: disk low (${FREE_PCT}% free). Starting cleanup..."

# Count processed images
PROCESSED_COUNT=$(find "$UPLOAD_DIR" -name "*.processed" 2>/dev/null | wc -l)
log "INFO: found $PROCESSED_COUNT processed image markers"

# Optional: backup to Google Drive before cleaning
if [ "$ENABLE_DRIVE_BACKUP" = "true" ]; then
  if command -v rclone >/dev/null 2>&1; then
    TS=$(date -u +"%Y%m%dT%H%M%SZ")
    DEST_PATH="${DRIVE_REMOTE}:uploads-${TS}"

    IONICE_CMD=""
    if command -v ionice >/dev/null 2>&1; then
      IONICE_CMD="ionice -c $IONICE_CLASS -n $IONICE_LEVEL"
    fi

    log "INFO: backing up to $DEST_PATH ..."
    if $IONICE_CMD nice -n "$NICE_LEVEL" rclone copy "$UPLOAD_DIR" "$DEST_PATH" \
      --drive-root-folder-id "$DRIVE_FOLDER_ID" \
      --create-empty-src-dirs \
      --checksum \
      --fast-list \
      --bwlimit "$BW_LIMIT" \
      --transfers 4 \
      --checkers 4 \
      --log-file "$LOG_FILE" \
      --log-level INFO; then
      log "INFO: backup complete to $DEST_PATH"
    else
      log "WARNING: rclone backup failed, continuing with cleanup anyway"
    fi
  else
    log "WARNING: rclone not installed, skipping backup"
  fi
fi

# Delete processed images (marker + corresponding jpg)
find "$UPLOAD_DIR" -name "*.processed" 2>/dev/null | while read -r marker; do
  jpg="${marker%.processed}"
  [ -f "$jpg" ] && rm -f "$jpg"
  rm -f "$marker"
done

# Delete empty directories
find "$UPLOAD_DIR" -mindepth 2 -type d -empty -delete 2>/dev/null || true

# Report
NEW_USED_PCT=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
NEW_FREE_PCT=$((100 - NEW_USED_PCT))
log "DONE: cleaned $PROCESSED_COUNT processed images. Disk now ${NEW_FREE_PCT}% free."

# Emergency: if still critically low (<10%), delete ALL images in unknown_device/
if [ "$NEW_FREE_PCT" -lt 10 ]; then
  log "CRITICAL: disk still at ${NEW_FREE_PCT}% free after cleanup!"
  if [ -d "$UPLOAD_DIR/unknown_device" ]; then
    find "$UPLOAD_DIR/unknown_device" -mindepth 1 -delete 2>/dev/null || true
    log "EMERGENCY: deleted all unknown_device images"
  fi
fi
```

### Criterios de aceite

1. `ENABLE_DRIVE_BACKUP=false` (default) → nao toca em rclone
2. `ENABLE_DRIVE_BACKUP=true` → tenta rclone, mas se falhar continua com cleanup
3. Limpa apenas imagens com marker `.processed` (nao apaga imagens nao processadas)
4. Limpeza de rotina (mesmo com espaco ok): apaga markers > 1h
5. Situacao critica (<10% livre): apaga `unknown_device/`
6. `UPLOAD_DIR` configuravel via env var
7. Script nao falha se rclone nao esta instalado

### Teste

```bash
# Teste sem backup (default)
UPLOAD_DIR=/tmp/test_uploads MIN_FREE_PERCENT=99 \
  bash services/scripts/backup_uploads_if_low_space.sh
# Deve entrar no modo cleanup (99% threshold garante que entra)

# Preparar teste
mkdir -p /tmp/test_uploads/cam_01/2026/02/08
touch /tmp/test_uploads/cam_01/2026/02/08/test.jpg
touch /tmp/test_uploads/cam_01/2026/02/08/test.jpg.processed

# Rodar
UPLOAD_DIR=/tmp/test_uploads MIN_FREE_PERCENT=99 ENABLE_DRIVE_BACKUP=false \
  bash services/scripts/backup_uploads_if_low_space.sh
# Verificar: test.jpg e test.jpg.processed devem ter sido deletados
ls /tmp/test_uploads/cam_01/2026/02/08/
# Esperado: vazio
```

---

## TAREFA 7: Seed de cameras reais no banco

**Prioridade:** MEDIA
**Arquivos a criar:** `services/backend/seed_cameras.py`
**Esforco:** Pequeno

### O que fazer

Criar script para popular a tabela `cameras` com os device_ids reais dos ESP32 em campo. Esse script deve ser idempotente (nao duplicar cameras).

### Codigo

```python
"""Seed real cameras into the database.

Usage:
    python seed_cameras.py

Reads CAMERAS list below and upserts into the cameras table.
Idempotent: safe to run multiple times.
"""
import asyncio
import os
import sys

# Add parent directory so we can import app modules
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select, text
from app.core.database import engine, AsyncSessionLocal
from app.models.camera import Camera


# ---- CONFIGURE YOUR CAMERAS HERE ----
CAMERAS = [
    {
        "name": "Camera 01 - Coque",
        "device_id": "cam_01_coque",
        "logradouro": "Rua Imperial, 200",
        "bairro": "Sao Jose",
        "rpa": "RPA 1",
        "latitude": -8.063170,
        "longitude": -34.871140,
    },
    # Add more cameras as needed:
    # {
    #     "name": "Camera 02 - Boa Viagem",
    #     "device_id": "cam_02_boaviagem",
    #     "logradouro": "Av. Boa Viagem, 1000",
    #     "bairro": "Boa Viagem",
    #     "rpa": "RPA 6",
    #     "latitude": -8.119740,
    #     "longitude": -34.896920,
    # },
]


async def seed():
    async with AsyncSessionLocal() as session:
        for cam_data in CAMERAS:
            result = await session.execute(
                select(Camera).where(Camera.device_id == cam_data["device_id"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                print(f"  Camera '{cam_data['device_id']}' already exists (id={existing.id}), skipping.")
                continue

            camera = Camera(**cam_data)
            session.add(camera)
            await session.commit()
            await session.refresh(camera)
            print(f"  Created camera '{cam_data['device_id']}' (id={camera.id})")

    print("Done.")


if __name__ == "__main__":
    print("Seeding cameras...")
    asyncio.run(seed())
```

### Criterios de aceite

1. Script cria cameras com `device_id` preenchido
2. Idempotente — rodar 2x nao duplica
3. Cameras aparecem na API `GET /api/v1/cameras`

### Teste

```bash
cd services/backend
python seed_cameras.py
# Esperado: "Created camera 'cam_01_coque' (id=X)"

python seed_cameras.py
# Esperado: "Camera 'cam_01_coque' already exists (id=X), skipping."
```

---

## ORDEM DE EXECUCAO

```text
Tarefa 4 (migration device_id)     ← primeiro: banco precisa estar pronto
    |
    v
Tarefa 7 (seed cameras)            ← popular cameras com device_id
    |
    v
Tarefa 3 (esp32-server device_id)  ← servidor organiza por device
    |
    v
Tarefa 1 (firmware header)         ← firmware envia device_id
    |
    v
Tarefa 2 (firmware fila PSRAM)     ← pode ser feito junto com 1
    |
    v
Tarefa 5 (fake worker)             ← precisa de tudo acima funcionando
    |
    v
Tarefa 6 (cleanup script)          ← complementar ao worker
```

**Tarefas paralelizaveis:**
- Tarefas 1+2 (firmware) podem ser feitas em paralelo com Tarefas 3+4+7 (server+backend)
- Tarefa 6 (cleanup) eh independente e pode ser feita a qualquer momento

---

## TESTE END-TO-END (apos todas as tarefas)

Sequencia para validar o pipeline completo:

```bash
# 1. Subir infraestrutura
cd services && docker-compose up -d   # backend + db + frontend
cd ../esp32-server && docker-compose up -d  # esp32-server

# 2. Aplicar migrations
cd ../services/backend && alembic upgrade head

# 3. Seed cameras
cd ../services/backend && python seed_cameras.py

# 4. Simular ESP32 enviando imagem
curl -X POST http://localhost:5001/upload \
  -H "X-Device-Id: cam_01_coque" \
  -F "imageFile=@test_image.jpg"
# Anotar o image_url retornado

# 5. Verificar imagem salva no path correto
ls esp32-server/uploads/cam_01_coque/
# Deve ter subdir YYYY/MM/DD/

# 6. Iniciar fake worker
cd services/yolo-worker-vm
export UPLOAD_DIR="../../esp32-server/uploads"
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/saira_db"
export PUBLIC_BASE_URL="http://localhost:5001"
export FAKE_MODE=true
python -m worker.main &

# 7. Aguardar processamento (~10s)
sleep 15

# 8. Verificar detection no banco
psql "postgresql://postgres:postgres@localhost:5432/saira_db" \
  -c "SELECT id, camera_id, waste_type, volume_m3, status, image_url FROM detections ORDER BY created_at DESC LIMIT 1;"
# Esperado: detection com image_url apontando para a imagem

# 9. Verificar no frontend
# Abrir http://localhost:3000 -> Ocorrencias
# Deve aparecer a deteccao com:
# - Logradouro, bairro, RPA da camera
# - Tipo de residuo (random)
# - Volume (random)
# - Status: Pendente
# - Foto clicavel (image_url)

# 10. Verificar marker de processado
ls esp32-server/uploads/cam_01_coque/2026/02/08/
# Deve ter: YYYY-MM-DD_HH-MM-SS.jpg E YYYY-MM-DD_HH-MM-SS.jpg.processed

# 11. Enviar outra imagem e verificar que o worker processa automaticamente
curl -X POST http://localhost:5001/upload \
  -H "X-Device-Id: cam_01_coque" \
  -F "imageFile=@test_image.jpg"
sleep 15
psql "postgresql://postgres:postgres@localhost:5432/saira_db" \
  -c "SELECT count(*) FROM detections;"
# Esperado: 2
```
