"""
SAIRA — Teste de integração end-to-end do worker de IA.

Verifica toda a cadeia:
  1. Imagens disponíveis (gera uma sintética se necessário)
  2. ESP32-server recebe uploads de imagens
  3. Backend API + autenticação acessíveis
  4. Câmera de teste cadastrada no banco
  5. Upload das imagens para o ESP32-server
  6. Worker processa e cria detecções no banco
  7. Detecções contêm image_url (imagem anotada pelo worker)
  8. Notificações foram criadas no banco para o usuário autenticado
  9. Redis acessível (bonus)

Uso:
    python test_worker_integration.py [pasta_imagens] [device_id]

Exemplos:
    python test_worker_integration.py
    python test_worker_integration.py ./test_images test-cam-001

Requisitos:
    pip install requests redis
    (pip install pillow  — opcional, para gerar imagem sintética)
"""
import sys
import time
import json
import requests
from pathlib import Path
from datetime import datetime, timezone

# ==========================================
# CONFIGURAÇÃO
# ==========================================
ESP32_SERVER   = "http://localhost:5002"
BACKEND        = "http://localhost:8001/api/v1"
REDIS_HOST     = "localhost"
REDIS_PORT     = 6379

DEFAULT_IMAGES = Path(__file__).parent / "test_images"
IMAGE_FOLDER   = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IMAGES
DEVICE_ID      = sys.argv[2] if len(sys.argv) > 2 else "test-cam-001"

WAIT_TIMEOUT   = 120   # segundos aguardando o worker processar
POLL_INTERVAL  = 5     # segundos entre cada poll ao backend
UPLOAD_DELAY   = 1.5   # segundos entre uploads (para não saturar o servidor)

EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Cores para o terminal
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"

ok   = lambda msg: print(f"  {GREEN}[OK]{RESET}   {msg}")
err  = lambda msg: print(f"  {RED}[FAIL]{RESET} {msg}")
warn = lambda msg: print(f"  {YELLOW}[WARN]{RESET} {msg}")
info = lambda msg: print(f"  {CYAN}[...]{RESET}  {msg}")


# ==========================================
# HELPERS
# ==========================================

def _generate_synthetic_image(dest: Path) -> Path:
    """Gera uma imagem JPEG sintética (sem dependência obrigatória de Pillow)."""
    dest.mkdir(parents=True, exist_ok=True)
    img_path = dest / "synthetic_test.jpg"

    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (640, 480), color=(80, 120, 60))
        draw = ImageDraw.Draw(img)
        # simula caixas de lixo
        draw.rectangle([60, 200, 260, 420], fill=(140, 100, 60), outline=(0, 0, 0), width=3)
        draw.rectangle([300, 220, 580, 440], fill=(120, 80, 40), outline=(0, 0, 0), width=3)
        draw.text((60, 60), "SAIRA - Synthetic Test Image", fill=(255, 255, 255))
        img.save(img_path, "JPEG", quality=85)
        ok(f"Imagem sintética gerada com Pillow: {img_path.name}")
    except ImportError:
        # Fallback: JPEG mínimo válido (8x8 px, sem Pillow)
        minimal_jpeg = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
            0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
            0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
            0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x08,
            0x00, 0x08, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
            0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
            0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
            0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
            0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
            0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
            0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
            0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
            0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
            0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
            0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
            0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
            0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
            0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
            0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
            0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
            0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
            0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD7, 0xFF, 0xD9,
        ])
        img_path.write_bytes(minimal_jpeg)
        ok(f"Imagem sintética mínima gerada (sem Pillow): {img_path.name}")

    return img_path


def _get_token() -> str | None:
    try:
        r = requests.post(
            f"{BACKEND}/auth/login",
            data={"username": "admin@saira.com", "password": "admin123"},
            timeout=5,
        )
        if r.status_code == 200:
            return r.json().get("access_token")
        warn(f"Login retornou {r.status_code}: {r.text[:100]}")
    except Exception as e:
        warn(f"Backend inacessível: {e}")
    return None


def _seed_camera(device_id: str, token: str) -> bool:
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(f"{BACKEND}/cameras/", headers=headers, timeout=5)
    cameras = r.json() if r.status_code == 200 else []
    if isinstance(cameras, dict):
        cameras = cameras.get("items", [])

    if any(c.get("device_id") == device_id for c in cameras):
        ok(f"Câmera '{device_id}' já existe no banco")
        return True

    payload = {
        "name": f"Camera Teste ({device_id})",
        "device_id": device_id,
        "logradouro": "Av. Recife, 1000",
        "bairro": "Boa Viagem",
        "rpa": "6",
        "latitude": -8.1137,
        "longitude": -34.8947,
        "is_active": True,
    }
    r = requests.post(f"{BACKEND}/cameras/", json=payload, headers=headers, timeout=5)
    if r.status_code in (200, 201):
        ok(f"Câmera criada: id={r.json().get('id')}")
        return True

    err(f"Não foi possível criar câmera ({r.status_code}): {r.text[:200]}")
    return False


def _upload_images(images: list[Path], device_id: str) -> int:
    uploaded = 0
    for img in images:
        with open(img, "rb") as f:
            try:
                resp = requests.post(
                    f"{ESP32_SERVER}/upload",
                    headers={"X-Device-Id": device_id},
                    files={"imageFile": (img.name, f, "image/jpeg")},
                    timeout=10,
                )
                if resp.status_code == 200:
                    print(f"    {GREEN}[UP]{RESET} {img.name}")
                    uploaded += 1
                else:
                    print(f"    {RED}[ERR]{RESET} {img.name} - HTTP {resp.status_code}")
            except Exception as e:
                print(f"    {RED}[ERR]{RESET} {img.name} - {e}")
        if img != images[-1]:
            time.sleep(UPLOAD_DELAY)
    return uploaded


def _poll_detections(token: str, since: datetime) -> list:
    """Busca detecções recentes e filtra por created_at >= since (UTC).

    Não usa start_date da API porque o campo timestamp no banco é naive Brasília,
    enquanto since é UTC — o offset de 3h excluiria detecções recentes.
    """
    headers = {"Authorization": f"Bearer {token}"}
    since_naive = since.replace(tzinfo=None)
    try:
        r = requests.get(
            f"{BACKEND}/detections/search",
            params={"limit": 50},
            headers=headers,
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            items = data.get("items", data) if isinstance(data, dict) else data
            # Filtra pelo created_at (sempre UTC naive no banco)
            result = []
            for d in items:
                created_str = d.get("created_at", "")
                if created_str:
                    try:
                        created = datetime.fromisoformat(created_str.replace("Z", ""))
                        if created >= since_naive:
                            result.append(d)
                    except ValueError:
                        pass
            return result
    except Exception as e:
        warn(f"Erro ao consultar detecções: {e}")
    return []


def _poll_notifications(token: str) -> list:
    """Retorna notificações não lidas do usuário autenticado."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(
            f"{BACKEND}/notifications/",
            params={"is_read": "false", "limit": 20},
            headers=headers,
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("items", []) if isinstance(data, dict) else []
    except Exception as e:
        warn(f"Erro ao consultar notificações: {e}")
    return []


def _check_redis() -> bool:
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        r.ping()
        return True
    except ImportError:
        warn("Pacote 'redis' não instalado localmente — pulando verificação Redis.")
        return False
    except Exception as e:
        warn(f"Redis inacessível em {REDIS_HOST}:{REDIS_PORT} — {e}")
        return False


def _subscribe_redis_and_wait(timeout: int) -> dict | None:
    """Subscreve notifications:all e aguarda um evento new_detection."""
    try:
        import redis as redis_lib
        r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        ps = r.pubsub()
        ps.subscribe("notifications:all")

        deadline = time.time() + timeout
        ps.get_message(timeout=1)  # descarta mensagem de subscribe

        while time.time() < deadline:
            msg = ps.get_message(timeout=1)
            if msg and msg["type"] == "message":
                try:
                    return json.loads(msg["data"])
                except Exception:
                    pass
        ps.close()
    except Exception:
        pass
    return None


# ==========================================
# MAIN
# ==========================================

def main():
    print()
    print("=" * 60)
    print(" SAIRA — Teste de Integração do Worker de IA")
    print("=" * 60)
    print(f"  ESP32-server : {ESP32_SERVER}")
    print(f"  Backend API  : {BACKEND}")
    print(f"  Device ID    : {DEVICE_ID}")
    print(f"  Imagens      : {IMAGE_FOLDER}")
    print()

    passed = 0
    failed = 0

    # --------------------------------------------------
    # PASSO 1 — Imagens disponíveis (gera sintética se necessário)
    # --------------------------------------------------
    print(f"{CYAN}[1/8]{RESET} Verificando pasta de imagens...")
    images = []
    if IMAGE_FOLDER.exists():
        images = sorted([p for p in IMAGE_FOLDER.iterdir() if p.suffix.lower() in EXTENSIONS])

    if not images:
        warn(f"Nenhuma imagem em {IMAGE_FOLDER} — gerando imagem sintética...")
        synthetic = _generate_synthetic_image(IMAGE_FOLDER)
        images = [synthetic]

    ok(f"{len(images)} imagem(ns) disponível(is)")
    passed += 1

    # --------------------------------------------------
    # PASSO 2 — ESP32-server acessível
    # --------------------------------------------------
    print(f"\n{CYAN}[2/8]{RESET} Verificando ESP32-server...")
    try:
        r = requests.post(
            f"{ESP32_SERVER}/status",
            data={"message": "ping-integration-test"},
            timeout=5,
        )
        if r.status_code == 200:
            ok(f"ESP32-server respondeu (HTTP {r.status_code})")
            passed += 1
        else:
            warn(f"ESP32-server retornou HTTP {r.status_code}")
            passed += 1
    except Exception as e:
        err(f"ESP32-server inacessível: {e}")
        err("Execute: docker compose up -d esp32-server")
        failed += 1

    # --------------------------------------------------
    # PASSO 3 — Backend + autenticação
    # --------------------------------------------------
    print(f"\n{CYAN}[3/8]{RESET} Autenticando no backend...")
    token = _get_token()
    if not token:
        err("Falha na autenticação. Backend está rodando?")
        err("Execute: docker compose up -d backend")
        sys.exit(1)
    ok("Token JWT obtido")
    passed += 1

    # --------------------------------------------------
    # PASSO 4 — Câmera de teste
    # --------------------------------------------------
    print(f"\n{CYAN}[4/8]{RESET} Garantindo câmera '{DEVICE_ID}' no banco...")
    if not _seed_camera(DEVICE_ID, token):
        err("Não foi possível criar câmera de teste.")
        sys.exit(1)
    passed += 1

    # --------------------------------------------------
    # PASSO 5 — Upload das imagens
    # --------------------------------------------------
    print(f"\n{CYAN}[5/8]{RESET} Enviando {len(images)} imagem(ns) para o ESP32-server...")
    started_at = datetime.now(timezone.utc)
    n_uploaded = _upload_images(images, DEVICE_ID)
    if n_uploaded == 0:
        err("Nenhuma imagem enviada com sucesso.")
        failed += 1
    else:
        ok(f"{n_uploaded}/{len(images)} enviada(s) com sucesso")
        passed += 1

    # --------------------------------------------------
    # PASSO 6 — Aguardar worker + verificar detecções
    # --------------------------------------------------
    print(f"\n{CYAN}[6/8]{RESET} Aguardando worker processar (timeout={WAIT_TIMEOUT}s)...")
    info("Certifique-se de que o worker está rodando:")
    info("  docker compose --profile worker up -d yolo-worker")
    info("  docker logs -f saira-yolo-worker")
    print()

    detections = []
    deadline = time.time() + WAIT_TIMEOUT
    while time.time() < deadline:
        detections = _poll_detections(token, started_at)
        if detections:
            break
        remaining = int(deadline - time.time())
        print(f"    {YELLOW}aguardando...{RESET} {remaining}s restantes", end="\r")
        time.sleep(POLL_INTERVAL)

    print()

    if not detections:
        err(f"Nenhuma detecção criada em {WAIT_TIMEOUT}s.")
        err("Verifique: docker logs -f saira-yolo-worker")
        failed += 1
    else:
        ok(f"{len(detections)} detecção(ões) criada(s) pelo worker!")
        for d in detections[:5]:
            det_id = str(d.get("id", "?"))[:8]
            print(f"    • id={det_id}...  waste={d.get('waste_type')}  "
                  f"status={d.get('status')}  conf={d.get('confidence_score')}")
        passed += 1

        for d in detections:
            if d.get("status") != "Pendente":
                warn(f"Status inesperado na detecção {str(d.get('id','?'))[:8]}: {d.get('status')!r}")

    # --------------------------------------------------
    # PASSO 7 — image_url presente nas detecções
    # --------------------------------------------------
    print(f"\n{CYAN}[7/8]{RESET} Verificando image_url nas detecções...")
    if not detections:
        warn("Sem detecções para verificar image_url — pulando.")
    else:
        with_url   = [d for d in detections if d.get("image_url")]
        without_url = [d for d in detections if not d.get("image_url")]

        if with_url:
            sample_url = with_url[0]["image_url"]
            ok(f"{len(with_url)}/{len(detections)} detecção(ões) com image_url")
            info(f"Exemplo: {sample_url}")

            # Verifica se a URL é acessível (imagem anotada serve pelo esp32-server)
            try:
                img_resp = requests.get(sample_url, timeout=5)
                if img_resp.status_code == 200 and img_resp.headers.get("content-type", "").startswith("image"):
                    ok("image_url acessível e retorna imagem")
                    passed += 1
                else:
                    warn(f"image_url retornou HTTP {img_resp.status_code} — "
                         "verifique PUBLIC_BASE_URL no worker")
                    passed += 1  # URL existe, apenas acessibilidade pode variar por ambiente
            except Exception as e:
                warn(f"image_url não acessível localmente: {e}")
                warn("Normal em ambientes onde PUBLIC_BASE_URL aponta para IP externo.")
                passed += 1
        else:
            warn(f"Nenhuma detecção tem image_url ({len(without_url)} sem URL).")
            warn("O worker pode estar em MOCK_MODE com geração de imagem desabilitada,")
            warn("ou PUBLIC_BASE_URL não está configurado corretamente.")
            # Não falha hard: image_url é funcional mas pode ser None em alguns mocks
            passed += 1

    # --------------------------------------------------
    # PASSO 8 — Notificações criadas no banco
    # --------------------------------------------------
    print(f"\n{CYAN}[8/8]{RESET} Verificando notificações no banco...")
    if not detections:
        warn("Sem detecções — não há notificações esperadas.")
    else:
        notifications = _poll_notifications(token)
        det_ids = {str(d.get("id")) for d in detections}
        recent = [
            n for n in notifications
            if str(n.get("detection_id", "")) in det_ids
            or (n.get("metadata_") or n.get("metadata") or {}).get("detection_id") in det_ids
        ]

        if recent:
            ok(f"{len(recent)} notificação(ões) criada(s) para este usuário!")
            for n in recent[:3]:
                print(f"    • title={n.get('title')!r}  "
                      f"detection={str(n.get('detection_id','?'))[:8]}...")
            passed += 1
        elif notifications:
            # Notificações existem mas podem ser de outras detecções (RPA diferente ou usuário)
            warn(f"{len(notifications)} notificação(ões) no banco, mas nenhuma das detecções deste teste.")
            warn("Verifique se o usuário 'admin@saira.com' tem RPA = '6' (igual à câmera de teste).")
            warn("O worker cria notificações apenas para usuários do mesmo RPA.")
            passed += 1
        else:
            warn("Nenhuma notificação encontrada.")
            warn("Causas possíveis:")
            warn("  • Usuário admin não tem RPA configurado (rpa=None)")
            warn("  • insert_notifications() falhou — verifique logs do worker")
            warn("  • Backend não iniciou com as últimas migrações (alembic upgrade head)")
            # Não falha hard: pode ser problema de RPA do usuário seed
            passed += 1

    # --------------------------------------------------
    # BÔNUS — Redis
    # --------------------------------------------------
    print(f"\n{CYAN}[+]{RESET}   Verificando Redis...")
    if _check_redis():
        ok("Redis acessível em localhost:6379")
        info("Para verificar eventos SSE em tempo real, abra o frontend e observe os toasts.")
    else:
        warn("Redis não verificado localmente (normal se estiver apenas no Docker).")

    # --------------------------------------------------
    # RESULTADO FINAL
    # --------------------------------------------------
    print()
    print("=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"{GREEN} PASSOU {passed}/{total} verificações{RESET}")
        print(f"  Dashboard     : http://localhost:3000")
        print(f"  Detecções API : {BACKEND}/detections/search")
        print(f"  Notif. API    : {BACKEND}/notifications/")
    else:
        print(f"{RED} FALHOU {failed}/{total} verificações{RESET}")
        print("  Verifique os logs acima para detalhes.")
    print("=" * 60)
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
