# PRD - Pesquisa de Implementação: Backend e Ingester SAÍRA

**Projeto:** SAÍRA - Sistema de Alerta Inteligente para Resíduos e Autuações
**Data:** 2026-02-03
**Escopo:** Implementação do Backend API e Ingester Service (Modo AWS/RTSP)

---

## 1. Resumo Executivo

### 1.1 Visão Geral do Sistema
O SAÍRA é um sistema de monitoramento de descarte irregular de lixo usando câmeras IP com processamento de IA na nuvem (AWS). A arquitetura é orientada a eventos e desacoplada, com três componentes principais:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Câmeras   │────▶│   Ingester  │────▶│  AWS SQS    │────▶│  AI Worker  │
│  IP/RTSP    │     │   Service   │     │    Queue    │     │   (YOLO)    │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                           │                                       │
                           ▼                                       ▼
                    ┌─────────────┐                         ┌─────────────┐
                    │  S3 Landing │                         │  S3 Evidence│
                    │    Zone     │                         │    + RDS    │
                    └─────────────┘                         └─────────────┘
                                                                   │
                                                                   ▼
                                                            ┌─────────────┐
                                                            │  Backend    │
                                                            │  FastAPI    │
                                                            └─────────────┘
                                                                   │
                                                                   ▼
                                                            ┌─────────────┐
                                                            │  Dashboard  │
                                                            │  + Alertas  │
                                                            └─────────────┘
```

### 1.2 O Que Precisa Ser Implementado

| Componente | Status Atual | A Implementar |
|------------|--------------|---------------|
| **Ingester - Modo Local (ADB)** | ✅ Completo | - |
| **Ingester - Modo AWS (RTSP)** | ❌ Placeholder | Captura RTSP, S3, SQS |
| **Backend - Auth** | ✅ Completo | - |
| **Backend - CRUD** | ✅ Completo | - |
| **Backend - Dashboard** | ✅ Completo | - |
| **Backend - Integração S3** | ⚠️ Configurado | Implementar acesso a imagens |

---

## 2. Arquivos da Base de Código Relevantes

### 2.1 Ingester Service

| Arquivo | Descrição | Relevância |
|---------|-----------|------------|
| [main.py](services/ingester/src/ingester/main.py) | Ponto de entrada. Modo `local` (ADB) ou `aws` | **CRÍTICO** - Implementar `main_aws()` |
| [s3.py](services/ingester/src/ingester/s3.py) | Placeholder para integração S3 | **CRÍTICO** - Arquivo vazio |
| [sqs.py](services/ingester/src/ingester/sqs.py) | Placeholder para integração SQS | **CRÍTICO** - Arquivo vazio |
| [cameras.py](services/ingester/src/ingester/cameras.py) | Placeholder para config de câmeras | **CRÍTICO** - Arquivo vazio |
| [config.py](services/ingester/src/ingester/config.py) | Configuração centralizada | Usar como base |
| [capture.py](services/ingester/src/ingester/local/capture.py) | Lógica de captura (ADB) | Padrões de resiliência |
| [image_validator.py](services/ingester/src/ingester/local/image_validator.py) | Validação de imagens | Reusar para RTSP |
| [pyproject.toml](services/ingester/pyproject.toml) | Dependências | Adicionar opencv, boto3, tenacity |

### 2.2 Backend API

| Arquivo | Descrição | Relevância |
|---------|-----------|------------|
| [main.py](services/backend/app/main.py) | App FastAPI | Já implementado |
| [config.py](services/backend/app/core/config.py) | Settings (S3, JWT, DB) | Configurações AWS |
| [database.py](services/backend/app/core/database.py) | AsyncSession PostgreSQL | Padrão a seguir |
| [security.py](services/backend/app/core/security.py) | JWT + Argon2 | Padrão de segurança |
| [deps.py](services/backend/app/api/deps.py) | Dependencies (auth, db) | Padrão DI |
| [detections.py](services/backend/app/api/v1/endpoints/detections.py) | CRUD de detecções | Endpoint principal |
| [geospatial_service.py](services/backend/app/services/geospatial_service.py) | Queries PostGIS | Reusar para buscas |
| [requirements.txt](services/backend/requirements.txt) | Dependências | boto3 já incluído |

---

## 3. Padrões de Implementação Encontrados na Base de Código

### 3.1 Padrão de Circuit Breaker (capture.py)

```python
# services/ingester/src/ingester/local/capture.py

class CameraCircuitBreaker:
    """Per-camera circuit breaker. Desabilita câmera após N falhas por cooldown."""

    def __init__(self, threshold: int, cooldown_s: float):
        self._threshold = threshold           # e.g., 3
        self._cooldown_s = cooldown_s         # e.g., 600s
        self._failures: dict[str, int] = {}
        self._disabled_until: dict[str, float] = {}

    def record_success(self, camera_name: str) -> None:
        self._failures[camera_name] = 0
        self._disabled_until.pop(camera_name, None)

    def record_failure(self, camera_name: str) -> None:
        count = self._failures.get(camera_name, 0) + 1
        self._failures[camera_name] = count
        if count >= self._threshold:
            until = time.monotonic() + self._cooldown_s
            self._disabled_until[camera_name] = until
            logger.warning(f"[CB] {camera_name} desabilitada por {self._cooldown_s}s")

    def is_available(self, camera_name: str) -> bool:
        until = self._disabled_until.get(camera_name)
        if until is None:
            return True
        if time.monotonic() >= until:
            self._disabled_until.pop(camera_name, None)
            self._failures[camera_name] = 0
            return True
        return False
```

**Uso:** Reusar este padrão para gerenciar falhas de conexão RTSP por câmera.

---

### 3.2 Padrão de Validação de Imagem (image_validator.py)

```python
# services/ingester/src/ingester/local/image_validator.py

def analyze_image(path: str) -> dict:
    """Computa estatísticas básicas em escala cinza"""
    with Image.open(path) as img:
        gray = img.convert("L").resize((64, 64))
        pixels = list(gray.getdata())
    mean = sum(pixels) / len(pixels)
    std = (sum((p - mean) ** 2 for p in pixels) / len(pixels)) ** 0.5
    return {"mean": round(mean, 2), "std": round(std, 2), "min": min(pixels), "max": max(pixels)}

def validate_screenshot(stats: dict) -> tuple[bool, str]:
    """Rejeita preto/branco"""
    if stats["mean"] <= 35 and stats["std"] <= 20:
        return False, "probable_black_screen"
    if stats["mean"] >= 240 and stats["std"] <= 20:
        return False, "probable_white_screen"
    return True, "ok"
```

**Uso:** Adaptar para validar frames RTSP (converter de numpy array para PIL Image).

---

### 3.3 Padrão de Async Database Session (database.py)

```python
# services/backend/app/core/database.py

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True if settings.ENVIRONMENT == "development" else False,
    future=True
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency para obter sessão do banco de dados"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
```

---

### 3.4 Padrão de Endpoint CRUD com Filtros (detections.py)

```python
# services/backend/app/api/v1/endpoints/detections.py

@router.get("/", response_model=List[DetectionResponse])
async def get_detections(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    rpa: Optional[str] = None,
    status_filter: Optional[DetectionStatus] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    bairro: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = select(Detection)
    filters = []

    if rpa:
        filters.append(Detection.rpa == rpa)
    if status_filter:
        filters.append(Detection.status == status_filter)
    if start_date:
        filters.append(Detection.timestamp >= datetime.combine(start_date, time.min))
    if end_date:
        filters.append(Detection.timestamp <= datetime.combine(end_date, time.max))
    if bairro:
        filters.append(Detection.bairro.ilike(f"%{bairro}%"))

    if filters:
        query = query.where(and_(*filters))

    query = query.offset(skip).limit(limit).order_by(Detection.timestamp.desc())
    result = await db.execute(query)
    return result.scalars().all()
```

---

## 4. Documentação de Tecnologias Externas

### 4.1 OpenCV RTSP com TCP Transport

**Problema:** O 4G perde pacotes UDP, causando artefatos cinzas na imagem.

**Solução:** Forçar TCP transport via variável de ambiente ANTES de criar o VideoCapture.

```python
import cv2
import os

# CRÍTICO: Configurar ANTES de criar VideoCapture
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'

RTSP_URL = 'rtsp://admin:saira123@10.8.0.5:554/cam/realmonitor?channel=1&subtype=0'
cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)

# Configurar timeout para evitar hang
cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)  # 10 segundos
cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)   # 5 segundos

if not cap.isOpened():
    raise ConnectionError(f"Falha ao conectar: {RTSP_URL}")

# Limpar buffer para pegar frame atual (não o primeiro do buffer)
for _ in range(5):
    cap.grab()

ret, frame = cap.read()
if ret:
    # frame é um numpy.ndarray (BGR)
    pass

cap.release()
```

**Fontes:**
- [Lindevs - Capture RTSP Stream](https://lindevs.com/capture-rtsp-stream-from-ip-camera-using-opencv)
- [PyShine - RTSP and OpenCV](https://www.pyshine.com/Real-time-streaming-protocol-and-opencv-in-Python/)
- [OpenCV Forum - RTSP TCP vs UDP](https://forum.opencv.org/t/why-is-it-still-tcp-when-i-using-opencv-python-rtsp-capture-option-udp/18475)

---

### 4.2 Boto3 S3 Upload com Best Practices

```python
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)

# Criar cliente S3 (usar IAM Role em produção, não access keys)
s3_client = boto3.client('s3', region_name='us-east-1')

# Configuração para uploads otimizados
transfer_config = TransferConfig(
    multipart_threshold=1024 * 1024 * 10,  # 10 MB (usar multipart acima disso)
    max_concurrency=8,
    use_threads=True
)

def upload_image_to_s3(
    file_path: str,
    bucket: str,
    key: str,
    content_type: str = "image/jpeg"
) -> str:
    """
    Faz upload de imagem para S3.

    Args:
        file_path: Caminho local do arquivo
        bucket: Nome do bucket S3
        key: Chave (path) do objeto no S3
        content_type: MIME type do arquivo

    Returns:
        URL do objeto no S3
    """
    try:
        s3_client.upload_file(
            Filename=file_path,
            Bucket=bucket,
            Key=key,
            Config=transfer_config,
            ExtraArgs={
                'ContentType': content_type,
                'Metadata': {
                    'source': 'ingester-v2',
                    'upload-timestamp': datetime.utcnow().isoformat()
                }
            }
        )
        logger.info(f"Upload successful: s3://{bucket}/{key}")
        return f"s3://{bucket}/{key}"

    except ClientError as e:
        logger.error(f"S3 upload failed: {e}")
        raise

def upload_bytes_to_s3(
    data: bytes,
    bucket: str,
    key: str,
    content_type: str = "image/jpeg"
) -> str:
    """Upload de bytes diretamente (sem salvar em disco)"""
    from io import BytesIO

    s3_client.upload_fileobj(
        Fileobj=BytesIO(data),
        Bucket=bucket,
        Key=key,
        ExtraArgs={'ContentType': content_type}
    )
    return f"s3://{bucket}/{key}"
```

**Fontes:**
- [Boto3 Official Docs - Uploading Files](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-uploading-files.html)
- [Real Python - Boto3 and S3](https://realpython.com/python-boto3-aws-s3/)
- [Medium - S3 Upload Performance](https://medium.com/@evaGachirwa/improving-s3-upload-performance-with-boto3-standard-multipart-and-acceleration-5544c8b7989c)

---

### 4.3 Boto3 SQS Send Message

```python
import boto3
import json
from datetime import datetime
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)

sqs_client = boto3.client('sqs', region_name='us-east-1')

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789/saira-ingestion-queue"

def send_ingestion_message(
    camera_id: str,
    s3_bucket: str,
    s3_key: str,
    metadata: dict
) -> str:
    """
    Envia mensagem para fila SQS após upload de imagem.

    Returns:
        MessageId da mensagem enviada
    """
    message_body = {
        "camera_id": camera_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "s3_bucket": s3_bucket,
        "s3_key": s3_key,
        "metadata": metadata
    }

    try:
        response = sqs_client.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps(message_body),
            MessageAttributes={
                'Source': {
                    'DataType': 'String',
                    'StringValue': 'ingester-v2'
                },
                'CameraId': {
                    'DataType': 'String',
                    'StringValue': camera_id
                }
            }
        )

        message_id = response['MessageId']
        logger.info(f"SQS message sent: {message_id}")
        return message_id

    except ClientError as e:
        logger.error(f"SQS send failed: {e}")
        raise

# Batch send para múltiplas mensagens (mais eficiente)
def send_batch_messages(messages: list[dict]) -> dict:
    """Envia até 10 mensagens em batch"""
    entries = [
        {
            'Id': str(i),
            'MessageBody': json.dumps(msg)
        }
        for i, msg in enumerate(messages[:10])
    ]

    response = sqs_client.send_message_batch(
        QueueUrl=QUEUE_URL,
        Entries=entries
    )

    return {
        'successful': len(response.get('Successful', [])),
        'failed': len(response.get('Failed', []))
    }
```

**Fontes:**
- [AWS Docs - SQS Examples](https://docs.aws.amazon.com/code-library/latest/ug/python_3_sqs_code_examples.html)
- [Boto3 Docs - SQS Guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/sqs-example-sending-receiving-msgs.html)
- [LearnAWS - SQS Boto3 Guide](https://www.learnaws.org/2020/12/17/aws-sqs-boto3-guide/)

---

### 4.4 Tenacity - Retry com Exponential Backoff

```python
from tenacity import (
    retry,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError
)
import logging
import cv2

logger = logging.getLogger(__name__)

# Padrão para conexões de rede (RTSP, S3, SQS)
@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError, cv2.error)),
    wait=wait_exponential(multiplier=1.5, min=2, max=30),
    stop=(stop_after_attempt(5) | stop_after_delay(60)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def connect_rtsp_with_retry(rtsp_url: str, timeout_ms: int = 10000) -> cv2.VideoCapture:
    """
    Conecta a stream RTSP com retry automático.

    - Retry em ConnectionError, TimeoutError e cv2.error
    - Exponential backoff: 2s, 3s, 4.5s, 6.75s, 10s (máx 30s)
    - Para após 5 tentativas OU 60 segundos
    """
    import os
    os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'

    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout_ms)

    if not cap.isOpened():
        raise ConnectionError(f"Falha ao abrir stream: {rtsp_url}")

    return cap

# Padrão para operações AWS (S3, SQS)
@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
def upload_with_retry(file_path: str, bucket: str, key: str):
    """Upload S3 com retry automático"""
    s3_client.upload_file(file_path, bucket, key)
```

**Fontes:**
- [Tenacity GitHub](https://github.com/jd/tenacity)
- [Tenacity Docs](https://tenacity.readthedocs.io/)
- [Towards Data Science - Tenacity Tutorial](https://towardsdatascience.com/conquer-retries-in-python-using-tenacity-an-in-depth-tutorial-3c98b216d798/)

---

### 4.5 FastAPI Async SQLAlchemy 2.0 Pattern

```python
# Padrão completo de Dependency Injection
from typing import Annotated, AsyncGenerator
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager

# Lifespan para inicialização/cleanup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database connection pool...")
    yield
    # Shutdown
    await engine.dispose()
    logger.info("Database connection pool closed")

app = FastAPI(lifespan=lifespan)

# Dependency tipada (melhor prática 2025)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# Alias para uso limpo nos endpoints
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]

# Endpoint usando os aliases
@router.get("/cameras/{camera_id}")
async def get_camera(
    camera_id: int,
    db: DbSession,
    user: CurrentUser
):
    result = await db.execute(
        select(Camera).where(Camera.id == camera_id)
    )
    camera = result.scalar_one_or_none()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera
```

**Fontes:**
- [FastAPI Best Practices 2025](https://orchestrator.dev/blog/2025-1-30-fastapi-production-patterns/)
- [DEV - Async Database Sessions](https://dev.to/akarshan/asynchronous-database-sessions-in-fastapi-with-sqlalchemy-1o7e)
- [Patterns and Practices SQLAlchemy 2.0](https://chaoticengineer.hashnode.dev/fastapi-sqlalchemy)

---

## 5. Schema de Dados (Conforme PRD_Ingester.md)

### 5.1 Configuração de Câmeras (cameras.yaml)

```yaml
# config/cameras.yaml
cameras:
  - id: "cam_01_coque"
    rpa: 1
    rtsp_url: "rtsp://admin:saira123@10.8.0.5:554/cam/realmonitor?channel=1&subtype=0"
    capture_interval_seconds: 300
    active: true

  - id: "cam_02_ilha_de_deus"
    rpa: 6
    rtsp_url: "rtsp://admin:saira123@10.8.0.6:554/live/ch0"
    capture_interval_seconds: 300
    active: true
```

### 5.2 Schema da Mensagem SQS

```json
{
  "camera_id": "cam_01_coque",
  "timestamp": "2025-10-25T14:30:00Z",
  "s3_bucket": "saira-landing-zone",
  "s3_key": "raw/2025/10/25/cam_01_coque_143000.jpg",
  "metadata": {
    "rpa": 1,
    "source_resolution": "1920x1080"
  }
}
```

### 5.3 Buckets S3 (Conforme Arquitetura)

| Bucket | Finalidade | Lifecycle |
|--------|-----------|-----------|
| `saira-landing-zone` | Imagens brutas do ingester | Exclusão em 24h |
| `saira-evidence-prod` | Imagens com infração confirmada | Standard 30d → IA 30d → Glacier 1a |
| `saira-dataset` | Amostras para re-treinamento | Indefinido |

---

## 6. Implementação Proposta: Ingester RTSP

### 6.1 Estrutura de Arquivos a Criar/Modificar

```
services/ingester/
├── config/
│   └── cameras.yaml          # CRIAR - Configuração de câmeras RTSP
├── src/ingester/
│   ├── main.py              # MODIFICAR - Adicionar main_aws()
│   ├── config.py            # MODIFICAR - Adicionar configs AWS
│   ├── s3.py                # IMPLEMENTAR - Upload S3
│   ├── sqs.py               # IMPLEMENTAR - Send SQS
│   ├── cameras.py           # IMPLEMENTAR - Load cameras.yaml
│   └── rtsp/                # CRIAR - Módulo RTSP
│       ├── __init__.py
│       ├── capture.py       # Captura RTSP com retry
│       └── validator.py     # Adaptação do image_validator
└── pyproject.toml           # MODIFICAR - Adicionar dependências
```

### 6.2 Dependências a Adicionar (pyproject.toml)

```toml
[tool.poetry.dependencies]
python = "^3.11"
pillow = "^10.4.0"
python-dotenv = "^1.0.0"
pyyaml = "^6.0"
# NOVAS DEPENDÊNCIAS
opencv-python-headless = "^4.9.0"  # Sem GUI
boto3 = "^1.34.0"
tenacity = "^8.2.0"
pydantic = "^2.5.0"
```

### 6.3 Código Proposto: rtsp/capture.py

```python
"""
Módulo de captura RTSP para o Ingester SAÍRA v2.0

Responsável por:
- Conectar a câmeras IP via RTSP
- Capturar frames em intervalos configurados
- Validar qualidade da imagem
- Fazer upload para S3 e notificar SQS
"""

import os
import cv2
import time
import logging
from datetime import datetime
from typing import Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

from tenacity import (
    retry,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from ..config import config
from ..s3 import upload_image_to_s3
from ..sqs import send_ingestion_message
from ..local.image_validator import analyze_image, validate_screenshot

logger = logging.getLogger(__name__)

# Forçar TCP para evitar perdas em 4G
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'


@dataclass
class CameraConfig:
    """Configuração de uma câmera"""
    id: str
    rpa: int
    rtsp_url: str
    capture_interval_seconds: int = 300
    active: bool = True


@dataclass
class CaptureResult:
    """Resultado de uma captura"""
    success: bool
    camera_id: str
    timestamp: datetime
    s3_key: Optional[str] = None
    error: Optional[str] = None
    validation_status: str = "unknown"


class RTSPCapture:
    """
    Classe para captura de frames RTSP com resiliência.

    Features:
    - Conexão com retry e exponential backoff
    - Limpeza de buffer para frame atual
    - Validação de imagem (não preta/branca)
    - Circuit breaker por câmera
    """

    def __init__(
        self,
        timeout_ms: int = 10000,
        read_timeout_ms: int = 5000,
        buffer_clear_frames: int = 5
    ):
        self.timeout_ms = timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self.buffer_clear_frames = buffer_clear_frames

        # Circuit breaker state
        self._failures: dict[str, int] = {}
        self._disabled_until: dict[str, float] = {}
        self._cb_threshold = config.CAMERA_CB_FAILURE_THRESHOLD
        self._cb_cooldown = config.CAMERA_CB_COOLDOWN_SECONDS

    def is_camera_available(self, camera_id: str) -> bool:
        """Verifica se câmera está disponível (circuit breaker)"""
        until = self._disabled_until.get(camera_id)
        if until is None:
            return True
        if time.monotonic() >= until:
            self._disabled_until.pop(camera_id, None)
            self._failures[camera_id] = 0
            logger.info(f"[CB] {camera_id} reabilitada")
            return True
        return False

    def record_success(self, camera_id: str):
        """Registra sucesso (reset circuit breaker)"""
        self._failures[camera_id] = 0
        self._disabled_until.pop(camera_id, None)

    def record_failure(self, camera_id: str):
        """Registra falha (incrementa circuit breaker)"""
        count = self._failures.get(camera_id, 0) + 1
        self._failures[camera_id] = count
        if count >= self._cb_threshold:
            until = time.monotonic() + self._cb_cooldown
            self._disabled_until[camera_id] = until
            logger.warning(
                f"[CB] {camera_id} desabilitada por {self._cb_cooldown}s "
                f"após {count} falhas"
            )

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError, cv2.error)),
        wait=wait_exponential(multiplier=1.5, min=2, max=30),
        stop=(stop_after_attempt(3) | stop_after_delay(45)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    def _connect(self, rtsp_url: str) -> cv2.VideoCapture:
        """Conecta a stream RTSP com retry"""
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.timeout_ms)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.read_timeout_ms)

        if not cap.isOpened():
            raise ConnectionError(f"Falha ao abrir stream: {rtsp_url}")

        return cap

    def capture_frame(self, camera: CameraConfig) -> Tuple[bool, Optional[bytes], str]:
        """
        Captura um frame de uma câmera.

        Returns:
            Tuple[success, jpeg_bytes, status_message]
        """
        if not self.is_camera_available(camera.id):
            return False, None, "camera_disabled_by_circuit_breaker"

        cap = None
        try:
            # Conectar com retry
            cap = self._connect(camera.rtsp_url)

            # Limpar buffer para pegar frame atual
            for _ in range(self.buffer_clear_frames):
                cap.grab()

            # Ler frame
            ret, frame = cap.read()
            if not ret or frame is None:
                raise ConnectionError("Falha ao ler frame")

            # Converter para JPEG em memória
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
            success, jpeg_buffer = cv2.imencode('.jpg', frame, encode_params)

            if not success:
                return False, None, "encode_failed"

            jpeg_bytes = jpeg_buffer.tobytes()

            # Validar imagem (não preta/branca)
            # Converter bytes para arquivo temporário para validação
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp.write(jpeg_bytes)
                tmp_path = tmp.name

            try:
                stats = analyze_image(tmp_path)
                is_valid, validation_status = validate_screenshot(stats)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            if not is_valid:
                self.record_failure(camera.id)
                return False, None, validation_status

            self.record_success(camera.id)
            return True, jpeg_bytes, "ok"

        except Exception as e:
            self.record_failure(camera.id)
            logger.error(f"Capture error {camera.id}: {e}")
            return False, None, str(e)

        finally:
            if cap is not None:
                cap.release()


def generate_s3_key(camera_id: str, timestamp: datetime) -> str:
    """Gera chave S3 no formato: raw/YYYY/MM/DD/camera_id_HHMMSS.jpg"""
    return (
        f"raw/{timestamp.strftime('%Y/%m/%d')}/"
        f"{camera_id}_{timestamp.strftime('%H%M%S')}.jpg"
    )


def run_capture_cycle(cameras: list[CameraConfig]) -> list[CaptureResult]:
    """
    Executa um ciclo de captura para todas as câmeras.

    Returns:
        Lista de resultados de captura
    """
    rtsp = RTSPCapture()
    results = []

    for camera in cameras:
        if not camera.active:
            continue

        timestamp = datetime.utcnow()
        logger.info(f"Capturing {camera.id}...")

        success, jpeg_bytes, status = rtsp.capture_frame(camera)

        result = CaptureResult(
            success=False,
            camera_id=camera.id,
            timestamp=timestamp,
            validation_status=status
        )

        if success and jpeg_bytes:
            try:
                # Upload para S3
                s3_key = generate_s3_key(camera.id, timestamp)
                upload_image_to_s3(
                    data=jpeg_bytes,
                    bucket=config.S3_LANDING_ZONE_BUCKET,
                    key=s3_key
                )

                # Notificar SQS
                send_ingestion_message(
                    camera_id=camera.id,
                    s3_bucket=config.S3_LANDING_ZONE_BUCKET,
                    s3_key=s3_key,
                    metadata={
                        "rpa": camera.rpa,
                        "source": "ingester-rtsp-v2"
                    }
                )

                result.success = True
                result.s3_key = s3_key
                logger.info(f"✓ {camera.id} -> s3://{config.S3_LANDING_ZONE_BUCKET}/{s3_key}")

            except Exception as e:
                result.error = str(e)
                logger.error(f"✗ {camera.id} upload/sqs error: {e}")
        else:
            result.error = status
            logger.warning(f"✗ {camera.id}: {status}")

        results.append(result)

    return results
```

---

## 7. Variáveis de Ambiente Necessárias

```bash
# .env do Ingester (Modo AWS)
INGESTER_MODE=aws

# AWS (usar IAM Role em produção, ou estas vars para dev)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1

# S3
S3_LANDING_ZONE_BUCKET=saira-landing-zone
S3_EVIDENCE_BUCKET=saira-evidence-prod

# SQS
SQS_INGESTION_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789/saira-ingestion-queue

# Resiliência
INGESTER_CAMERA_CB_FAILURE_THRESHOLD=3
INGESTER_CAMERA_CB_COOLDOWN_SECONDS=600
INGESTER_CAPTURE_INTERVAL_SECONDS=300
INGESTER_MAX_CONSECUTIVE_FAILURES=10
```

---

## 8. Checklist de Implementação

### 8.1 Ingester - Modo AWS/RTSP

- [ ] Criar `config/cameras.yaml` com configuração de câmeras
- [ ] Implementar `cameras.py` - loader do YAML
- [ ] Implementar `s3.py` - upload com retry
- [ ] Implementar `sqs.py` - send message com retry
- [ ] Criar módulo `rtsp/capture.py` - captura com circuit breaker
- [ ] Adaptar `image_validator.py` para bytes/numpy
- [ ] Implementar `main_aws()` em `main.py`
- [ ] Atualizar `pyproject.toml` com novas dependências
- [ ] Atualizar `Dockerfile` para incluir libgl (OpenCV)
- [ ] Criar testes unitários
- [ ] Testar localmente com câmera RTSP real

### 8.2 Backend API

- [ ] Verificar endpoint para receber notificação do AI Worker
- [ ] Implementar endpoint para servir imagens do S3 (presigned URL)
- [ ] Adicionar filtro por `confidence_score` em detections
- [ ] Implementar webhook/notificação para Telegram

---

## 10. Integração Frontend-Backend

### 10.1 Arquivos do Frontend Relevantes

| Arquivo | Descrição | Status |
|---------|-----------|--------|
| [api.ts](services/frontend/src/services/api.ts) | Configuração Axios, interceptors | ✅ Configurado |
| [AuthContext.tsx](services/frontend/src/contexts/AuthContext.tsx) | Context de autenticação | ✅ Integrado |
| [mockData.ts](services/frontend/src/services/mockData.ts) | **Dados simulados de detecções** | ❌ Precisa migrar para API |
| [Dashboard.tsx](services/frontend/src/pages/Dashboard.tsx) | Página principal | ⚠️ Usa dados mock |
| [Detections.tsx](services/frontend/src/pages/Detections.tsx) | Tabela de detecções | ⚠️ Usa dados mock |
| [UsersPage.tsx](services/frontend/src/pages/UsersPage.tsx) | CRUD de usuários | ⚠️ Usa dados mock |
| [Login.tsx](services/frontend/src/pages/Login.tsx) | **Login hardcoded** | ⚠️ Bypass de auth |

### 10.2 Dados Mockados Identificados

#### **Login (Login.tsx:56-57)** - BYPASS HARDCODED
```typescript
// PROBLEMA: Login fake sem chamar API
if (email === "admin@gmail.com" && password === "12345") {
  navigate("/dashboard");  // Pula autenticação real!
}
```
**Solução:** Usar `useAuth().signIn()` do AuthContext que já está implementado.

---

#### **Detecções (mockData.ts)** - DADOS SIMULADOS

```typescript
// 9 localizações fixas de Recife
const seedLocations: SeedLocation[] = [
  { bairro: "Imbiribeira", logradouro: "Rua Visconde de Suassuna", ... },
  { bairro: "Brasília Teimosa", logradouro: "Av. Brasília Formosa", ... },
  // ...mais 7 locais
];

// Gera ~1000 registros fake
const generateMockData = (): PoiData[] => { ... }

export const masterPois: PoiData[] = generateMockData();
```

**Usado em:**
- `Dashboard.tsx` - importa `masterPois`
- `Detections.tsx` - importa `masterPois`

---

#### **Usuários (UsersPage.tsx:21-132)** - ARRAY HARDCODED
```typescript
const INITIAL_USERS = [
  { id: 1, name: "João Victor...", email: "joao.santos@recife.pe.gov.br", ... },
  { id: 2, name: "Maria Eduarda...", email: "maria.lima@recife.pe.gov.br", ... },
  // ...mais 9 usuários
];
```

---

### 10.3 Comparação de Schemas: Frontend vs Backend

#### **Detection/PoiData - INCOMPATIBILIDADES CRÍTICAS**

| Campo Frontend | Campo Backend | Tipo Frontend | Tipo Backend | Gap |
|----------------|---------------|---------------|--------------|-----|
| `id` | `id` | `string` ("SAIRA-0001") | `UUID` | ⚠️ Formato diferente |
| `wasteType` | `waste_type` | `string` | `string` | ⚠️ camelCase vs snake_case |
| `volume` | `volume_m3` | `number` | `Decimal` | ⚠️ Nome diferente |
| `photoUrl` | `image_url` | `string` | `string` | ⚠️ Nome diferente |
| `hasOffender` | `offenders` | `boolean` | `string` | ❌ Tipo diferente |
| `status` | `status` | `string` | `Enum` | ⚠️ Verificar valores |
| - | `camera_id` | - | `int` | Frontend não usa |
| - | `confidence_score` | - | `Decimal` | Frontend não usa |
| - | `material_type` | - | `string` | Frontend não usa |
| - | `created_at` | - | `datetime` | Frontend não usa |
| `rpa` | `rpa` | `string` (via table) | `string` | ✅ OK |

---

#### **Frontend PoiData Interface:**
```typescript
// services/frontend/src/services/mockData.ts
export type PoiData = {
  id: string;                                    // "SAIRA-0001"
  bairro: string;
  logradouro: string;
  latitude: number;
  longitude: number;
  timestamp: string;
  wasteType: "Entulho" | "Lixo domiciliar" | "Poda" | "Plástico";
  volume: number;
  status: "Pendente" | "Em análise" | "Resolvido";
  photoUrl: string;
  hasOffender: boolean;
};
```

#### **Backend DetectionResponse Schema:**
```python
# services/backend/app/schemas/detection.py
class DetectionResponse(DetectionBase):
    id: UUID                           # UUID, não string formatada
    camera_id: Optional[int]
    timestamp: datetime
    logradouro: Optional[str]
    bairro: Optional[str]
    rpa: Optional[str]
    latitude: Decimal
    longitude: Decimal
    waste_type: Optional[str]          # snake_case
    material_type: Optional[str]
    volume_m3: Optional[Decimal]       # nome diferente
    offenders: Optional[str]           # string, não boolean
    status: DetectionStatus            # Enum
    image_url: Optional[str]           # nome diferente
    confidence_score: Optional[Decimal]
    created_at: datetime
    updated_at: datetime
```

---

#### **User - COMPATÍVEL COM AJUSTES MENORES**

| Campo Frontend | Campo Backend | Status |
|----------------|---------------|--------|
| `id` | `id` | ✅ OK (int) |
| `name` | `name` | ✅ OK |
| `email` | `email` | ✅ OK |
| `phone` | `phone` | ✅ OK |
| `secretaria` | `secretaria` | ✅ OK |
| `cargo` | `cargo` | ✅ OK |
| `rpa` | `rpa` | ✅ OK |
| `is_active` | `is_active` | ✅ OK |
| `status` ("Ativo"/"Inativo") | - | ⚠️ Frontend usa string, backend usa `is_active: bool` |

---

#### **Status Enum - INCONSISTÊNCIA NO BACKEND**

```python
# Model (detection.py) - UPPERCASE
class DetectionStatus(str, enum.Enum):
    PENDENTE = "PENDENTE"
    EM_ANALISE = "EM_ANALISE"
    RESOLVIDO = "RESOLVIDO"

# Schema (schemas/detection.py) - Capitalizado
class DetectionStatus(str, Enum):
    PENDENTE = "Pendente"
    EM_ANALISE = "Em análise"
    RESOLVIDO = "Resolvido"
```

**Frontend espera:**
```typescript
status: "Pendente" | "Em análise" | "Resolvido"
```

**Solução:** Padronizar no backend para usar os valores do schema (capitalizados).

---

### 10.4 Endpoints Necessários vs Disponíveis

| Funcionalidade | Endpoint Backend | Status | Frontend Usa |
|----------------|------------------|--------|--------------|
| Login | `POST /auth/login` | ✅ | ⚠️ Bypass |
| Dados usuário | `GET /auth/me` | ✅ | ✅ |
| Listar detecções | `GET /detections` | ✅ | ❌ Usa mock |
| Detalhe detecção | `GET /detections/{id}` | ✅ | ❌ Usa mock |
| Atualizar status | `PATCH /detections/{id}` | ✅ | ❌ Usa mock |
| Dashboard stats | `GET /dashboard/stats` | ✅ | ❌ Calcula local |
| Ocorrências/mês | `GET /dashboard/occurrences-by-month` | ✅ | ❌ Calcula local |
| Locais reincidentes | `GET /dashboard/recurrent-locations` | ✅ | ❌ Calcula local |
| Volume por RPA | `GET /dashboard/volume-by-rpa` | ✅ | ❌ Calcula local |
| Listar usuários | `GET /users` | ✅ | ❌ Usa mock |
| Criar usuário | `POST /users` | ✅ | ❌ Usa mock |
| Atualizar usuário | `PATCH /users/{id}` | ✅ | ❌ Usa mock |
| Deletar usuário | `DELETE /users/{id}` | ✅ | ❌ Usa mock |
| Listar câmeras | `GET /cameras` | ✅ | ❌ Não usado |

---

### 10.5 Alterações Necessárias no Banco de Dados

#### **NENHUMA ALTERAÇÃO DE SCHEMA NECESSÁRIA**

O modelo de dados do backend já contempla todos os campos necessários. As diferenças são apenas de nomenclatura/formato que devem ser tratadas no frontend ou via serialização.

#### **Sugestão: Adicionar Campo Computado**

Para facilitar a integração, pode-se adicionar um campo `display_id` no backend:

```python
# Opção 1: Property no model
@property
def display_id(self) -> str:
    """ID formatado para exibição: SAIRA-0001"""
    return f"SAIRA-{str(self.id)[:8].upper()}"

# Opção 2: Campo computado no schema response
class DetectionResponse(DetectionBase):
    id: UUID

    @computed_field
    @property
    def display_id(self) -> str:
        return f"SAIRA-{str(self.id)[:8].upper()}"
```

---

### 10.6 Plano de Migração Frontend

#### **Fase 1: Criar Service Layer**

```typescript
// services/frontend/src/services/detectionService.ts

import api from './api';

export interface Detection {
  id: string;
  display_id?: string;
  camera_id?: number;
  timestamp: string;
  logradouro?: string;
  bairro?: string;
  rpa?: string;
  latitude: number;
  longitude: number;
  waste_type?: string;
  volume_m3?: number;
  offenders?: string;
  status: 'Pendente' | 'Em análise' | 'Resolvido';
  image_url?: string;
  confidence_score?: number;
}

// Adapter: converte backend -> frontend
function toFrontendFormat(detection: Detection): PoiData {
  return {
    id: detection.display_id || detection.id,
    bairro: detection.bairro || '',
    logradouro: detection.logradouro || '',
    latitude: detection.latitude,
    longitude: detection.longitude,
    timestamp: detection.timestamp,
    wasteType: detection.waste_type as WasteType || 'Entulho',
    volume: detection.volume_m3 || 0,
    status: detection.status,
    photoUrl: detection.image_url || '',
    hasOffender: !!detection.offenders,
  };
}

export async function getDetections(params?: {
  skip?: number;
  limit?: number;
  rpa?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  bairro?: string;
}): Promise<PoiData[]> {
  const response = await api.get('/detections', { params });
  return response.data.map(toFrontendFormat);
}

export async function updateDetectionStatus(
  id: string,
  status: string
): Promise<Detection> {
  const response = await api.patch(`/detections/${id}`, { status });
  return response.data;
}
```

---

#### **Fase 2: Criar Dashboard Service**

```typescript
// services/frontend/src/services/dashboardService.ts

import api from './api';

export interface DashboardStats {
  total_occurrences: number;
  daily_volume_m3: number;
  pending_count: number;
  in_analysis_count: number;
  resolved_count: number;
}

export interface OccurrencesByMonth {
  month: string;
  count: number;
}

export interface RecurrentLocation {
  logradouro: string;
  bairro: string;
  rpa: string;
  count: number;
}

export interface VolumeByRPA {
  rpa: string;
  avg_volume_m3: number;
  total_volume_m3: number;
  count: number;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await api.get('/dashboard/stats');
  return response.data;
}

export async function getOccurrencesByMonth(): Promise<OccurrencesByMonth[]> {
  const response = await api.get('/dashboard/occurrences-by-month');
  return response.data;
}

export async function getRecurrentLocations(): Promise<RecurrentLocation[]> {
  const response = await api.get('/dashboard/recurrent-locations');
  return response.data;
}

export async function getVolumeByRPA(): Promise<VolumeByRPA[]> {
  const response = await api.get('/dashboard/volume-by-rpa');
  return response.data;
}
```

---

#### **Fase 3: Criar User Service**

```typescript
// services/frontend/src/services/userService.ts

import api from './api';

export interface User {
  id: number;
  name: string;
  email: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface CreateUserData {
  name: string;
  email: string;
  password: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
  is_active?: boolean;
}

// Adapter: adiciona campo "status" para compatibilidade
function addStatusField(user: User): User & { status: string } {
  return {
    ...user,
    status: user.is_active ? 'Ativo' : 'Inativo',
  };
}

export async function getUsers(params?: {
  skip?: number;
  limit?: number;
  search?: string;
  rpa?: string;
  cargo?: string;
  is_active?: boolean;
}): Promise<(User & { status: string })[]> {
  const response = await api.get('/users', { params });
  return response.data.map(addStatusField);
}

export async function createUser(data: CreateUserData): Promise<User> {
  const response = await api.post('/users', data);
  return response.data;
}

export async function updateUser(
  id: number,
  data: Partial<CreateUserData>
): Promise<User> {
  const response = await api.patch(`/users/${id}`, data);
  return response.data;
}

export async function deleteUser(id: number): Promise<void> {
  await api.delete(`/users/${id}`);
}
```

---

#### **Fase 4: Atualizar Componentes**

```typescript
// Exemplo: Dashboard.tsx

// ANTES (mock)
import { masterPois } from '../services/mockData';

// DEPOIS (API)
import { useState, useEffect } from 'react';
import { getDetections } from '../services/detectionService';
import { getDashboardStats, getOccurrencesByMonth } from '../services/dashboardService';

function Dashboard() {
  const [detections, setDetections] = useState<PoiData[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [detectionsData, statsData] = await Promise.all([
          getDetections({ limit: 1000 }),
          getDashboardStats(),
        ]);
        setDetections(detectionsData);
        setStats(statsData);
      } catch (error) {
        console.error('Erro ao carregar dados:', error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  // ... resto do componente
}
```

---

#### **Fase 5: Corrigir Login**

```typescript
// Login.tsx - ANTES (bypass)
const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  if (email === "admin@gmail.com" && password === "12345") {
    navigate("/dashboard");
  }
};

// Login.tsx - DEPOIS (API real)
import { useAuth } from '../contexts/AuthContext';

const { signIn } = useAuth();

const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoading(true);
  try {
    await signIn({ email, password });
    navigate("/dashboard");
  } catch (error) {
    setError("Email ou senha incorretos.");
  } finally {
    setLoading(false);
  }
};
```

---

### 10.7 Checklist de Integração Frontend-Backend

#### **Backend (Ajustes)**
- [ ] Padronizar `DetectionStatus` enum (model vs schema)
- [ ] Adicionar campo `display_id` no DetectionResponse (opcional)
- [ ] Verificar CORS está configurado para frontend
- [ ] Adicionar endpoint para presigned URL de imagens S3

#### **Frontend (Implementação)**
- [ ] Criar `detectionService.ts` com adapter
- [ ] Criar `dashboardService.ts`
- [ ] Criar `userService.ts` com adapter
- [ ] Remover import de `mockData.ts` do Dashboard.tsx
- [ ] Remover import de `mockData.ts` do Detections.tsx
- [ ] Remover `INITIAL_USERS` do UsersPage.tsx
- [ ] Corrigir Login.tsx para usar `useAuth().signIn()`
- [ ] Adicionar estados de loading/error em todos componentes
- [ ] Adicionar tratamento de erro 401 (já no interceptor)
- [ ] Configurar `VITE_API_URL` no `.env`

#### **Testes**
- [ ] Testar login com credenciais reais
- [ ] Testar listagem de detecções com filtros
- [ ] Testar CRUD de usuários
- [ ] Testar endpoints de dashboard
- [ ] Testar atualização de status de detecção

---

## 11. Referências

### Documentação Oficial
- [Boto3 S3 Upload](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3-uploading-files.html)
- [Boto3 SQS Guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/sqs-example-sending-receiving-msgs.html)
- [Tenacity Docs](https://tenacity.readthedocs.io/)
- [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)

### Tutoriais e Best Practices
- [OpenCV RTSP Capture](https://lindevs.com/capture-rtsp-stream-from-ip-camera-using-opencv)
- [Real Python - Boto3 S3](https://realpython.com/python-boto3-aws-s3/)
- [FastAPI Best Practices 2025](https://orchestrator.dev/blog/2025-1-30-fastapi-production-patterns/)
- [Tenacity Tutorial](https://towardsdatascience.com/conquer-retries-in-python-using-tenacity-an-in-depth-tutorial-3c98b216d798/)
- [Async SQLAlchemy Patterns](https://chaoticengineer.hashnode.dev/fastapi-sqlalchemy)

### Código de Referência (Base de Código SAÍRA)
- Circuit Breaker: [capture.py:CameraCircuitBreaker](services/ingester/src/ingester/local/capture.py)
- Image Validation: [image_validator.py](services/ingester/src/ingester/local/image_validator.py)
- Async DB Session: [database.py](services/backend/app/core/database.py)
- CRUD Pattern: [detections.py](services/backend/app/api/v1/endpoints/detections.py)
