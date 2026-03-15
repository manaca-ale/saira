# SPEC - SAIRA: Implementacao Ingester RTSP + Integracao Frontend

**Baseado em:** PRD.md
**Data:** 2026-02-03

---

## 1. INGESTER SERVICE - Modo AWS/RTSP

### 1.1 Arquivos a CRIAR

| Arquivo | Descricao |
|---------|-----------|
| `services/ingester/config/cameras.yaml` | Configuracao de cameras RTSP |
| `services/ingester/src/ingester/rtsp/__init__.py` | Init do modulo RTSP |
| `services/ingester/src/ingester/rtsp/capture.py` | Captura RTSP com circuit breaker e retry |

---

#### `services/ingester/config/cameras.yaml`

```yaml
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

---

#### `services/ingester/src/ingester/rtsp/__init__.py`

```python
from .capture import RTSPCapture, CaptureResult, run_capture_cycle

__all__ = ["RTSPCapture", "CaptureResult", "run_capture_cycle"]
```

---

#### `services/ingester/src/ingester/rtsp/capture.py`

Implementar classe `RTSPCapture` com:
- Circuit breaker por camera (reusar padrao de `local/capture.py`)
- Retry com tenacity (exponential backoff)
- Forcar TCP transport via `os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'`
- Limpar buffer antes de capturar (5 frames de grab)
- Validacao de imagem (reusar `image_validator.py`)
- Funcao `run_capture_cycle(cameras)` que orquestra captura -> S3 -> SQS

```python
"""
Modulo de captura RTSP para o Ingester SAIRA v2.0

Responsavel por:
- Conectar a cameras IP via RTSP
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

# Forcar TCP para evitar perdas em 4G
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'


@dataclass
class CameraConfig:
    """Configuracao de uma camera"""
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
    Classe para captura de frames RTSP com resiliencia.

    Features:
    - Conexao com retry e exponential backoff
    - Limpeza de buffer para frame atual
    - Validacao de imagem (nao preta/branca)
    - Circuit breaker por camera
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
        """Verifica se camera esta disponivel (circuit breaker)"""
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
                f"apos {count} falhas"
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
        Captura um frame de uma camera.

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

            # Converter para JPEG em memoria
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]
            success, jpeg_buffer = cv2.imencode('.jpg', frame, encode_params)

            if not success:
                return False, None, "encode_failed"

            jpeg_bytes = jpeg_buffer.tobytes()

            # Validar imagem (nao preta/branca)
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
    Executa um ciclo de captura para todas as cameras.

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
                logger.info(f"OK {camera.id} -> s3://{config.S3_LANDING_ZONE_BUCKET}/{s3_key}")

            except Exception as e:
                result.error = str(e)
                logger.error(f"FAIL {camera.id} upload/sqs error: {e}")
        else:
            result.error = status
            logger.warning(f"FAIL {camera.id}: {status}")

        results.append(result)

    return results
```

---

### 1.2 Arquivos a MODIFICAR

| Arquivo | O que fazer |
|---------|-------------|
| `services/ingester/src/ingester/s3.py` | Implementar (arquivo vazio) |
| `services/ingester/src/ingester/sqs.py` | Implementar (arquivo vazio) |
| `services/ingester/src/ingester/cameras.py` | Implementar (arquivo vazio) |
| `services/ingester/src/ingester/config.py` | Adicionar configs AWS |
| `services/ingester/src/ingester/main.py` | Adicionar `main_aws()` |
| `services/ingester/pyproject.toml` | Adicionar dependencias |

---

#### `services/ingester/src/ingester/s3.py`

```python
import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
from io import BytesIO
from datetime import datetime

from .config import config

logger = logging.getLogger(__name__)

s3_client = boto3.client('s3', region_name=config.AWS_REGION)

transfer_config = TransferConfig(
    multipart_threshold=1024 * 1024 * 10,
    max_concurrency=8,
    use_threads=True
)

@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3)
)
def upload_image_to_s3(
    data: bytes,
    bucket: str,
    key: str,
    content_type: str = "image/jpeg"
) -> str:
    """Upload de bytes para S3 com retry."""
    s3_client.upload_fileobj(
        Fileobj=BytesIO(data),
        Bucket=bucket,
        Key=key,
        ExtraArgs={
            'ContentType': content_type,
            'Metadata': {
                'source': 'ingester-rtsp-v2',
                'upload-timestamp': datetime.utcnow().isoformat()
            }
        }
    )
    logger.info(f"Upload: s3://{bucket}/{key}")
    return f"s3://{bucket}/{key}"
```

---

#### `services/ingester/src/ingester/sqs.py`

```python
import boto3
import json
from datetime import datetime
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

from .config import config

logger = logging.getLogger(__name__)

sqs_client = boto3.client('sqs', region_name=config.AWS_REGION)

@retry(
    retry=retry_if_exception_type(ClientError),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3)
)
def send_ingestion_message(
    camera_id: str,
    s3_bucket: str,
    s3_key: str,
    metadata: dict
) -> str:
    """Envia mensagem para fila SQS apos upload."""
    message_body = {
        "camera_id": camera_id,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "s3_bucket": s3_bucket,
        "s3_key": s3_key,
        "metadata": metadata
    }

    response = sqs_client.send_message(
        QueueUrl=config.SQS_INGESTION_QUEUE_URL,
        MessageBody=json.dumps(message_body),
        MessageAttributes={
            'Source': {'DataType': 'String', 'StringValue': 'ingester-rtsp-v2'},
            'CameraId': {'DataType': 'String', 'StringValue': camera_id}
        }
    )
    logger.info(f"SQS message: {response['MessageId']}")
    return response['MessageId']
```

---

#### `services/ingester/src/ingester/cameras.py`

```python
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List
import logging

logger = logging.getLogger(__name__)

@dataclass
class CameraConfig:
    id: str
    rpa: int
    rtsp_url: str
    capture_interval_seconds: int = 300
    active: bool = True

def load_cameras(config_path: str = "config/cameras.yaml") -> List[CameraConfig]:
    """Carrega configuracao de cameras do YAML."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config nao encontrado: {config_path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    cameras = [CameraConfig(**cam) for cam in data.get("cameras", [])]
    active = [c for c in cameras if c.active]
    logger.info(f"Carregadas {len(active)}/{len(cameras)} cameras ativas")
    return cameras
```

---

#### `services/ingester/src/ingester/config.py`

**Adicionar** as seguintes configuracoes:

```python
# AWS
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
S3_LANDING_ZONE_BUCKET: str = os.getenv("S3_LANDING_ZONE_BUCKET", "saira-landing-zone")
SQS_INGESTION_QUEUE_URL: str = os.getenv("SQS_INGESTION_QUEUE_URL", "")

# RTSP Capture
CAMERA_CB_FAILURE_THRESHOLD: int = int(os.getenv("INGESTER_CAMERA_CB_FAILURE_THRESHOLD", "3"))
CAMERA_CB_COOLDOWN_SECONDS: float = float(os.getenv("INGESTER_CAMERA_CB_COOLDOWN_SECONDS", "600"))
CAPTURE_INTERVAL_SECONDS: int = int(os.getenv("INGESTER_CAPTURE_INTERVAL_SECONDS", "300"))
MAX_CONSECUTIVE_FAILURES: int = int(os.getenv("INGESTER_MAX_CONSECUTIVE_FAILURES", "10"))
```

---

#### `services/ingester/src/ingester/main.py`

**Adicionar** funcao `main_aws()`:

```python
import asyncio
import time
import logging

from .cameras import load_cameras
from .rtsp.capture import run_capture_cycle
from .config import config

logger = logging.getLogger(__name__)

def main_aws():
    """Loop principal do ingester em modo AWS/RTSP."""
    logger.info("Iniciando Ingester em modo AWS/RTSP")

    cameras = load_cameras()
    active_cameras = [c for c in cameras if c.active]

    if not active_cameras:
        logger.error("Nenhuma camera ativa configurada!")
        return

    consecutive_failures = 0

    while True:
        try:
            results = run_capture_cycle(active_cameras)

            successes = sum(1 for r in results if r.success)
            failures = len(results) - successes

            logger.info(f"Ciclo completo: {successes} OK, {failures} falhas")

            if successes > 0:
                consecutive_failures = 0
            else:
                consecutive_failures += 1

            if consecutive_failures >= config.MAX_CONSECUTIVE_FAILURES:
                logger.critical(f"{consecutive_failures} ciclos sem sucesso. Encerrando.")
                break

        except Exception as e:
            logger.exception(f"Erro no ciclo: {e}")
            consecutive_failures += 1

        time.sleep(config.CAPTURE_INTERVAL_SECONDS)

# No if __name__ == "__main__" existente, adicionar:
# if mode == "aws":
#     main_aws()
```

---

#### `services/ingester/pyproject.toml`

**Adicionar** em `[tool.poetry.dependencies]`:

```toml
opencv-python-headless = "^4.9.0"
boto3 = "^1.34.0"
tenacity = "^8.2.0"
pydantic = "^2.5.0"
pyyaml = "^6.0"
```

---

## 2. FRONTEND - Integracao com API Real

### 2.1 Arquivos a CRIAR

| Arquivo | Descricao |
|---------|-----------|
| `services/frontend/src/services/detectionService.ts` | Service + adapter para deteccoes |
| `services/frontend/src/services/dashboardService.ts` | Service para endpoints de dashboard |
| `services/frontend/src/services/userService.ts` | Service + adapter para usuarios |

---

#### `services/frontend/src/services/detectionService.ts`

```typescript
import api from './api';

export interface Detection {
  id: string;
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
  status: 'Pendente' | 'Em analise' | 'Resolvido';
  image_url?: string;
  confidence_score?: number;
}

export interface PoiData {
  id: string;
  bairro: string;
  logradouro: string;
  latitude: number;
  longitude: number;
  timestamp: string;
  wasteType: string;
  volume: number;
  status: string;
  photoUrl: string;
  hasOffender: boolean;
}

function toFrontendFormat(d: Detection): PoiData {
  return {
    id: d.id,
    bairro: d.bairro || '',
    logradouro: d.logradouro || '',
    latitude: d.latitude,
    longitude: d.longitude,
    timestamp: d.timestamp,
    wasteType: d.waste_type || 'Entulho',
    volume: d.volume_m3 || 0,
    status: d.status,
    photoUrl: d.image_url || '',
    hasOffender: !!d.offenders,
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

export async function updateDetectionStatus(id: string, status: string): Promise<Detection> {
  const response = await api.patch(`/detections/${id}`, { status });
  return response.data;
}
```

---

#### `services/frontend/src/services/dashboardService.ts`

```typescript
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

export const getDashboardStats = () => api.get<DashboardStats>('/dashboard/stats').then(r => r.data);
export const getOccurrencesByMonth = () => api.get<OccurrencesByMonth[]>('/dashboard/occurrences-by-month').then(r => r.data);
export const getRecurrentLocations = () => api.get<RecurrentLocation[]>('/dashboard/recurrent-locations').then(r => r.data);
export const getVolumeByRPA = () => api.get<VolumeByRPA[]>('/dashboard/volume-by-rpa').then(r => r.data);
```

---

#### `services/frontend/src/services/userService.ts`

```typescript
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
}

export interface CreateUserData {
  name: string;
  email: string;
  password: string;
  phone?: string;
  secretaria?: string;
  cargo?: string;
  rpa?: string;
}

function addStatusField(user: User): User & { status: string } {
  return { ...user, status: user.is_active ? 'Ativo' : 'Inativo' };
}

export async function getUsers(params?: { skip?: number; limit?: number }): Promise<(User & { status: string })[]> {
  const response = await api.get('/users', { params });
  return response.data.map(addStatusField);
}

export const createUser = (data: CreateUserData) => api.post<User>('/users', data).then(r => r.data);
export const updateUser = (id: number, data: Partial<CreateUserData>) => api.patch<User>(`/users/${id}`, data).then(r => r.data);
export const deleteUser = (id: number) => api.delete(`/users/${id}`);
```

---

### 2.2 Arquivos a MODIFICAR

| Arquivo | O que fazer |
|---------|-------------|
| `services/frontend/src/pages/Login.tsx` | Remover bypass hardcoded, usar `useAuth().signIn()` |
| `services/frontend/src/pages/Dashboard.tsx` | Remover import de `mockData`, usar `detectionService` + `dashboardService` |
| `services/frontend/src/pages/Detections.tsx` | Remover import de `mockData`, usar `detectionService` |
| `services/frontend/src/pages/UsersPage.tsx` | Remover `INITIAL_USERS`, usar `userService` |

---

#### `services/frontend/src/pages/Login.tsx`

**REMOVER** (linhas ~56-57):
```typescript
if (email === "admin@gmail.com" && password === "12345") {
  navigate("/dashboard");
}
```

**SUBSTITUIR POR**:
```typescript
import { useAuth } from '../contexts/AuthContext';

// Dentro do componente:
const { signIn } = useAuth();

const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoading(true);
  setError('');
  try {
    await signIn({ email, password });
    navigate("/dashboard");
  } catch (err) {
    setError("Email ou senha incorretos.");
  } finally {
    setLoading(false);
  }
};
```

---

#### `services/frontend/src/pages/Dashboard.tsx`

**REMOVER**:
```typescript
import { masterPois } from '../services/mockData';
```

**ADICIONAR**:
```typescript
import { useState, useEffect } from 'react';
import { getDetections, PoiData } from '../services/detectionService';
import { getDashboardStats, getOccurrencesByMonth, DashboardStats } from '../services/dashboardService';

// No componente:
const [detections, setDetections] = useState<PoiData[]>([]);
const [stats, setStats] = useState<DashboardStats | null>(null);
const [loading, setLoading] = useState(true);

useEffect(() => {
  async function load() {
    try {
      const [data, statsData] = await Promise.all([
        getDetections({ limit: 1000 }),
        getDashboardStats()
      ]);
      setDetections(data);
      setStats(statsData);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }
  load();
}, []);
```

**Usar** `detections` em vez de `masterPois` no resto do componente.

---

#### `services/frontend/src/pages/Detections.tsx`

Mesma logica do Dashboard:
- Remover `import { masterPois }`
- Adicionar `useEffect` com `getDetections()`
- Substituir `masterPois` por estado local

---

#### `services/frontend/src/pages/UsersPage.tsx`

**REMOVER** (linhas ~21-132):
```typescript
const INITIAL_USERS = [ ... ];
```

**SUBSTITUIR POR**:
```typescript
import { useState, useEffect } from 'react';
import { getUsers, createUser, updateUser, deleteUser, User } from '../services/userService';

const [users, setUsers] = useState<(User & { status: string })[]>([]);
const [loading, setLoading] = useState(true);

useEffect(() => {
  getUsers().then(setUsers).finally(() => setLoading(false));
}, []);

// Handlers CRUD chamam as funcoes do service e atualizam estado
```

---

## 3. BACKEND - Ajustes Menores

### 3.1 Arquivos a MODIFICAR

| Arquivo | O que fazer |
|---------|-------------|
| `services/backend/app/models/detection.py` | Padronizar enum para usar valores capitalizados |
| `services/backend/app/schemas/detection.py` | Verificar consistencia com model |

---

#### `services/backend/app/models/detection.py`

**ALTERAR** enum para usar valores capitalizados (compativeis com frontend):

```python
class DetectionStatus(str, enum.Enum):
    PENDENTE = "Pendente"
    EM_ANALISE = "Em analise"
    RESOLVIDO = "Resolvido"
```

---

## 4. VARIAVEIS DE AMBIENTE

### Ingester `.env`:
```bash
INGESTER_MODE=aws
AWS_REGION=us-east-1
S3_LANDING_ZONE_BUCKET=saira-landing-zone
SQS_INGESTION_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/XXXX/saira-ingestion-queue
INGESTER_CAMERA_CB_FAILURE_THRESHOLD=3
INGESTER_CAMERA_CB_COOLDOWN_SECONDS=600
INGESTER_CAPTURE_INTERVAL_SECONDS=300
```

### Frontend `.env`:
```bash
VITE_API_URL=http://localhost:8000/api/v1
```

---

## 5. RESUMO DE ARQUIVOS

| Acao | Qtd | Arquivos |
|------|-----|----------|
| **CRIAR** | 6 | `cameras.yaml`, `rtsp/__init__.py`, `rtsp/capture.py`, `detectionService.ts`, `dashboardService.ts`, `userService.ts` |
| **MODIFICAR** | 11 | `s3.py`, `sqs.py`, `cameras.py`, `config.py`, `main.py`, `pyproject.toml`, `Login.tsx`, `Dashboard.tsx`, `Detections.tsx`, `UsersPage.tsx`, `models/detection.py` |

---

## 6. ORDEM DE IMPLEMENTACAO SUGERIDA

### Fase 1: Ingester RTSP (Backend)
1. `pyproject.toml` - adicionar dependencias
2. `config.py` - adicionar configs AWS
3. `cameras.py` - loader YAML
4. `s3.py` - upload S3
5. `sqs.py` - send SQS
6. `config/cameras.yaml` - config cameras
7. `rtsp/__init__.py` + `rtsp/capture.py` - captura RTSP
8. `main.py` - adicionar `main_aws()`

### Fase 2: Frontend Services
1. `detectionService.ts`
2. `dashboardService.ts`
3. `userService.ts`

### Fase 3: Frontend Pages
1. `Login.tsx` - corrigir auth
2. `Dashboard.tsx` - integrar API
3. `Detections.tsx` - integrar API
4. `UsersPage.tsx` - integrar API

### Fase 4: Backend Ajustes
1. `models/detection.py` - padronizar enum
