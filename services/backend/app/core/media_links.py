"""Links assinados para foto e vídeo das ocorrências.

Até 24/11/2026 `/uploads/*` e `/s3-images/*` do site (proxy do nginx do frontend para o esp32-server
e para o S3) e as URLs diretas do bucket abriam sem login. Agora o backend devolve cada foto e vídeo
como caminho do próprio site com `?md5=...&expires=...`, e o nginx confere a assinatura com o módulo
`secure_link` (`secure_link_md5 "$secure_link_expires$uri <segredo>"`).

A assinatura é determinística dentro de cada janela de `MEDIA_LINK_TTL_SECONDS`: o mesmo arquivo dá
o mesmo link na mesma janela (o painel compara a URL da foto salva com a dos quadros) e o link vale
entre 1 e 2 janelas. Sem `MEDIA_LINK_SECRET` (desenvolvimento) o caminho sai sem assinatura.
"""
from __future__ import annotations

import base64
import hashlib
import re
import time
from typing import Optional
from urllib.parse import unquote, urlsplit

from app.core.config import settings

_S3_HOST = re.compile(r"^[^/]+\.s3[.-][^/]*amazonaws\.com$")


def canonical_media_path(url: Optional[str]) -> Optional[str]:
    """Caminho do site para uma foto ou vídeo, sem query; None se não for mídia nossa.

    https://saira-images.s3.sa-east-1.amazonaws.com/ocorrencias/x.jpg -> /s3-images/ocorrencias/x.jpg
    http://localhost:5005/uploads/esp32_004/x.jpg                    -> /uploads/esp32_004/x.jpg
    /s3-images/ocorrencias/x.jpg?md5=..&expires=..                   -> /s3-images/ocorrencias/x.jpg
    """
    if not url:
        return None
    parts = urlsplit(str(url).strip())
    path = parts.path
    if parts.netloc and _S3_HOST.match(parts.netloc) and path.startswith("/") and len(path) > 1:
        return "/s3-images" + path
    if path.startswith("/s3-images/"):
        return path
    idx = path.find("/uploads/")
    if idx >= 0:
        return path[idx:]
    return None


def strip_media_signature(url: Optional[str]) -> Optional[str]:
    """Tira `md5`/`expires` de um link nosso antes de gravar no banco; o resto passa igual."""
    if not url:
        return url
    if canonical_media_path(url) is None:
        return url
    parts = urlsplit(str(url).strip())
    if not parts.query:
        return url
    kept = [p for p in parts.query.split("&") if p and p.split("=", 1)[0] not in ("md5", "expires")]
    base = str(url).strip().split("?", 1)[0]
    return base + ("?" + "&".join(kept) if kept else "")


def _expires(now: float, ttl: int) -> int:
    return (int(now) // ttl + 2) * ttl


def media_signature(path: str, expires: int, secret: str) -> str:
    """O mesmo cálculo do `secure_link_md5 "$secure_link_expires$uri <segredo>"` do nginx."""
    raw = f"{expires}{unquote(path)} {secret}".encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.md5(raw).digest()).decode("ascii").rstrip("=")


def sign_media_url(url: Optional[str], now: Optional[float] = None) -> Optional[str]:
    """Link assinado do site para foto ou vídeo; URL que não é mídia nossa volta igual."""
    path = canonical_media_path(url)
    if path is None:
        return url
    secret = settings.MEDIA_LINK_SECRET
    if not secret:
        return path
    ttl = max(60, int(settings.MEDIA_LINK_TTL_SECONDS))
    expires = _expires(time.time() if now is None else now, ttl)
    return f"{path}?md5={media_signature(path, expires, secret)}&expires={expires}"
