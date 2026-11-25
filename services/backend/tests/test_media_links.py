"""Regressão: fotos e vídeos das ocorrências abriam sem login (achado em 24/11/2026).

`saira.manaca.tech/uploads/*` (inclusive `server-events.jsonl`) e `/s3-images/*` eram proxies abertos
do nginx do frontend, e a API devolvia a URL pública do bucket. Agora a API devolve links do site com
`?md5=...&expires=...`, que o nginx confere com `secure_link`. Estes testes cobrem o cálculo (igual ao
do nginx), a assinatura na saída da API e a limpeza da assinatura antes de gravar no banco.
"""
import uuid
from datetime import datetime

import pytest

from app.core import media_links
from app.core.config import settings
from app.schemas.camera import CameraLatestImageResponse
from app.schemas.detection import (
    DetectionAnalyzedFrame,
    DetectionResponse,
    DetectionUpdate,
    DetectionVideoResponse,
)

S3_URL = "https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/pi-cam-001/2026/08/01/2026-08-01_15-40-54.jpg"
PATH = "/s3-images/ocorrencias/pi-cam-001/2026/08/01/2026-08-01_15-40-54.jpg"
AGORA = 1700000000  # janela de 3600 s: expires = 1700006400


@pytest.fixture
def segredo(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_LINK_SECRET", "segredo-de-teste")
    monkeypatch.setattr(settings, "MEDIA_LINK_TTL_SECONDS", 3600)


@pytest.mark.parametrize(
    "url,esperado",
    [
        (S3_URL, PATH),
        (PATH, PATH),
        (PATH + "?md5=abc&expires=1", PATH),
        ("http://localhost:5005/uploads/esp32_004/2026/05/01/x.jpg", "/uploads/esp32_004/2026/05/01/x.jpg"),
        ("/uploads/videos/pi-cam-001/evt-20260723_061455.mp4", "/uploads/videos/pi-cam-001/evt-20260723_061455.mp4"),
        ("https://exemplo.com/foto.jpg", None),
        ("", None),
        (None, None),
    ],
)
def test_caminho_canonico(url, esperado):
    assert media_links.canonical_media_path(url) == esperado


def test_assinatura_igual_a_do_nginx(segredo):
    # Valor de referência gerado com o comando da documentação do secure_link:
    # echo -n "1700006400<uri> segredo-de-teste" | openssl md5 -binary | openssl base64 | tr +/ -_ | tr -d =
    assert media_links.sign_media_url(S3_URL, now=AGORA) == f"{PATH}?md5=mvqIX4cIdXdXFzd_VovoQA&expires=1700006400"


def test_mesmo_link_na_mesma_janela_e_validade_de_pelo_menos_uma_janela(segredo):
    a = media_links.sign_media_url(S3_URL, now=AGORA)
    b = media_links.sign_media_url(PATH, now=AGORA + 500)
    assert a == b  # o painel compara a foto salva com a dos quadros
    expires = int(a.rsplit("expires=", 1)[1])
    assert expires - (AGORA + 500) >= 3600


def test_sem_segredo_sai_o_caminho_sem_assinatura(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_LINK_SECRET", "")
    assert media_links.sign_media_url(S3_URL) == PATH


def test_url_de_fora_nao_muda(segredo):
    assert media_links.sign_media_url("https://exemplo.com/foto.jpg") == "https://exemplo.com/foto.jpg"


def test_tira_a_assinatura_e_mantem_o_resto():
    assert media_links.strip_media_signature(PATH + "?md5=abc&expires=1") == PATH
    assert media_links.strip_media_signature(PATH + "?md5=abc&t=9&expires=1") == PATH + "?t=9"
    assert media_links.strip_media_signature(S3_URL) == S3_URL
    assert media_links.strip_media_signature("https://exemplo.com/x?md5=1") == "https://exemplo.com/x?md5=1"


def _deteccao(image_url):
    agora = datetime(2026, 8, 1, 15, 40)
    return DetectionResponse(
        id=uuid.uuid4(), timestamp=agora, latitude=-8.05, longitude=-34.87, image_url=image_url,
        created_at=agora, updated_at=agora,
    )


def test_api_devolve_foto_assinada(segredo):
    saida = _deteccao(S3_URL).model_dump(mode="json")
    assert saida["image_url"].startswith(PATH + "?md5=")
    assert "amazonaws.com" not in saida["image_url"]


def test_quadros_video_e_camera_saem_assinados(segredo):
    quadro = DetectionAnalyzedFrame(frame_name="x.jpg", image_url=PATH).model_dump(mode="json")
    video = DetectionVideoResponse(
        detection_id=uuid.uuid4(), status="available", video_url="/uploads/videos/pi-cam-001/evt-1.mp4"
    ).model_dump(mode="json")
    camera = CameraLatestImageResponse(camera_id=1, image_url="/uploads/pi-cam-001/x.jpg").model_dump(mode="json")
    assert "?md5=" in quadro["image_url"]
    assert video["video_url"].startswith("/uploads/videos/pi-cam-001/evt-1.mp4?md5=")
    assert camera["image_url"].startswith("/uploads/pi-cam-001/x.jpg?md5=")


def test_trocar_o_quadro_grava_o_caminho_sem_assinatura(segredo):
    assinado = media_links.sign_media_url(PATH)
    assert DetectionUpdate(image_url=assinado).image_url == PATH
