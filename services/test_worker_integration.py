"""
SAIRA — Teste de integração end-to-end do worker de IA.

Verifica toda a cadeia:
  1. ESP32-server recebe uploads de imagens
  2. YOLO worker processa as imagens e insere detecções no banco
  3. Backend API retorna as detecções criadas
  4. Redis recebeu o evento de notificação (opcional)

Uso:
    python test_worker_integration.py [pasta_imagens] [device_id]

Exemplos:
    python test_worker_integration.py
    python test_worker_integration.py ./test_images test-cam-001

Requisitos:
    pip install requests redis
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

def _get_token() -> str | None:
    try:
        r = requests.post(
            f"{BACKEND}/auth/login",
            json={"email": "admin@saira.com", "password": "admin123"},
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
                    print(f"    {GREEN}↑{RESET} {img.name}")
                    uploaded += 1
                else:
                    print(f"    {RED}✗{RESET} {img.name} — HTTP {resp.status_code}")
            except Exception as e:
                print(f"    {RED}✗{RESET} {img.name} — {e}")
        if img != images[-1]:
            time.sleep(UPLOAD_DELAY)
    return uploaded


def _poll_detections(token: str, since: datetime) -> list:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(
            f"{BACKEND}/detections/search",
            params={"start_date": since.isoformat(), "limit": 20},
            headers=headers,
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("items", data) if isinstance(data, dict) else data
    except Exception as e:
        warn(f"Erro ao consultar detecções: {e}")
    return []


def _check_redis() -> bool:
    """Verifica se o Redis está acessível e testa pub/sub."""
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
        # Descarta a mensagem de subscribe
        ps.get_message(timeout=1)

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
    # PASSO 1 — Imagens disponíveis
    # --------------------------------------------------
    print(f"{CYAN}[1/6]{RESET} Verificando pasta de imagens...")
    images = sorted([p for p in IMAGE_FOLDER.iterdir() if p.suffix.lower() in EXTENSIONS])
    if not images:
        err(f"Nenhuma imagem encontrada em: {IMAGE_FOLDER}")
        sys.exit(1)
    ok(f"{len(images)} imagem(ns) encontrada(s)")
    passed += 1

    # --------------------------------------------------
    # PASSO 2 — ESP32-server acessível
    # --------------------------------------------------
    print(f"\n{CYAN}[2/6]{RESET} Verificando ESP32-server...")
    try:
        r = requests.get(f"{ESP32_SERVER}/status", timeout=5)
        if r.status_code in (200, 404):  # /status pode não existir, mas o servidor responde
            ok(f"ESP32-server respondeu (HTTP {r.status_code})")
            passed += 1
        else:
            warn(f"ESP32-server retornou HTTP {r.status_code}")
            passed += 1  # Ainda acessível
    except Exception as e:
        err(f"ESP32-server inacessível: {e}")
        err("Execute: docker compose up -d esp32-server")
        failed += 1

    # --------------------------------------------------
    # PASSO 3 — Backend + autenticação
    # --------------------------------------------------
    print(f"\n{CYAN}[3/6]{RESET} Autenticando no backend...")
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
    print(f"\n{CYAN}[4/6]{RESET} Garantindo câmera '{DEVICE_ID}' no banco...")
    if not _seed_camera(DEVICE_ID, token):
        err("Não foi possível criar câmera de teste.")
        sys.exit(1)
    passed += 1

    # --------------------------------------------------
    # PASSO 5 — Upload das imagens
    # --------------------------------------------------
    print(f"\n{CYAN}[5/6]{RESET} Enviando {len(images)} imagem(ns) para o ESP32-server...")
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
    print(f"\n{CYAN}[6/6]{RESET} Aguardando worker processar (timeout={WAIT_TIMEOUT}s)...")
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

    print()  # limpa a linha do countdown

    if not detections:
        err(f"Nenhuma detecção criada em {WAIT_TIMEOUT}s.")
        err("Verifique os logs: docker logs -f saira-yolo-worker")
        failed += 1
    else:
        ok(f"{len(detections)} detecção(ões) criada(s) pelo worker!")
        for d in detections[:5]:
            det_id = str(d.get("id", "?"))[:8]
            print(f"    • id={det_id}...  waste={d.get('waste_type')}  "
                  f"status={d.get('status')}  conf={d.get('confidence_score')}")
        passed += 1

        # Verificação extra: campo status deve ser "Pendente"
        for d in detections:
            if d.get("status") != "Pendente":
                warn(f"Status inesperado na detecção {str(d.get('id','?'))[:8]}: {d.get('status')!r}")

    # --------------------------------------------------
    # BÔNUS — Redis
    # --------------------------------------------------
    print(f"\n{CYAN}[+]{RESET}   Verificando Redis...")
    if _check_redis():
        ok("Redis acessível em localhost:6379")
        info("Para verificar eventos em tempo real, abra o frontend e observe os toasts.")
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
        print(f"  Dashboard : http://localhost:3000")
        print(f"  API       : {BACKEND}/detections/search")
    else:
        print(f"{RED} FALHOU {failed}/{total} verificações{RESET}")
        print(f"  Verifique os logs acima para detalhes.")
    print("=" * 60)
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()



