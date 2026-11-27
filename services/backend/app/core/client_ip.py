"""IP de quem chamou, para os limites por endereço e o registro dos links.

Em produção e no teste o caminho é Cloudflare → cloudflared → nginx do web →
uvicorn. O uvicorn roda com --proxy-headers e --forwarded-allow-ips="*", e
assim põe em request.client o endereço MAIS À ESQUERDA do X-Forwarded-For.
Esse primeiro endereço é escrito pelo próprio visitante: a Cloudflare e o nginx
só acrescentam à direita. Conferido no teste em 27/11/2026: um
"X-Forwarded-For: 203.0.113.77" chegava ao backend como o IP do cliente, e o
limite por IP do "esqueci minha senha" deixava de valer.

Aqui o X-Forwarded-For é lido da direita para a esquerda, pulando os endereços
que não são públicos (o nginx e a rede do Docker); o primeiro público é o que a
Cloudflare viu, e o visitante não consegue escrever à direita dele.
"""
from __future__ import annotations

import ipaddress

from starlette.requests import Request


def _is_public(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        # Não é IP (porta junto, lixo): ninguém da nossa cadeia escreve isso,
        # então conta como o primeiro endereço de fora.
        return True


def client_ip(request: Request) -> str:
    entries = [item.strip() for item in request.headers.get("x-forwarded-for", "").split(",")]
    entries = [item for item in entries if item]
    for item in reversed(entries):
        if _is_public(item):
            return item
    if entries:
        # Cadeia só de rede interna (compose local, rede da Manacá).
        return entries[0]
    return request.client.host if request.client else "desconhecido"
