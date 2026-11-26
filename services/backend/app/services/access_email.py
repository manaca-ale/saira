"""E-mails de acesso: convite, recuperação de senha e aviso de senha alterada.

Português, HTML simples mais versão texto. Nenhum leva senha; os links são de
uso único (app.services.access_service).
"""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape
from typing import Optional

from app.core.config import settings
from app.core.timezone import BRAZIL_TIMEZONE
from app.services import email_service

logger = logging.getLogger(__name__)


def _first_name(name: Optional[str]) -> str:
    return (name or "").strip().split(" ")[0] or "olá"


def _html(paragraphs: list[str], link: Optional[str] = None, button: str = "") -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs[:1])
    if link:
        body += (
            f'<p><a href="{escape(link, quote=True)}"><b>{escape(button)}</b></a></p>'
            f'<p>Se o botão não abrir, copie e cole este endereço no navegador:<br>{escape(link)}</p>'
        )
    body += "".join(f"<p>{p}</p>" for p in paragraphs[1:])
    body += "<p>Equipe SAÍRA</p>"
    return f"<html><body>{body}</body></html>"


def _hours_text(hours: int) -> str:
    return "1 hora" if hours == 1 else f"{hours} horas"


def _minutes_text(minutes: int) -> str:
    if minutes % 60 == 0:
        return _hours_text(minutes // 60)
    return f"{minutes} minutos"


def build_invite_email(name: str, link: str, invited_by: Optional[str]) -> tuple[str, str, str]:
    validity = _hours_text(settings.ACCESS_INVITE_TTL_HOURS)
    who = f"{invited_by} criou" if invited_by else "Foi criado"
    first = _first_name(name)
    subject = "Seu acesso ao SAÍRA"
    intro = (
        f"Olá, {first}! {who} um acesso para você no SAÍRA, o painel de "
        "monitoramento de descarte irregular. Para entrar, crie a sua senha pelo link abaixo."
    )
    rest = [
        f"O link vale por {validity} e só pode ser usado uma vez. Se ele vencer, "
        "peça um novo ao administrador.",
        "Ninguém da equipe vai pedir a sua senha. Se você não esperava este e-mail, pode ignorá-lo.",
    ]
    html = _html([escape(intro)] + [escape(p) for p in rest], link, "Criar minha senha")
    text = "\n\n".join([intro, f"Criar minha senha: {link}", *rest, "Equipe SAÍRA"])
    return subject, html, text


def build_reset_email(name: str, link: str) -> tuple[str, str, str]:
    validity = _minutes_text(settings.PASSWORD_RESET_TTL_MINUTES)
    first = _first_name(name)
    subject = "Redefinir sua senha do SAÍRA"
    intro = f"Olá, {first}! Recebemos um pedido para redefinir a sua senha do SAÍRA."
    rest = [
        f"O link vale por {validity} e só pode ser usado uma vez.",
        "Se não foi você que pediu, ignore este e-mail: a sua senha atual continua a mesma.",
    ]
    html = _html([escape(intro)] + [escape(p) for p in rest], link, "Criar uma senha nova")
    text = "\n\n".join([intro, f"Criar uma senha nova: {link}", *rest, "Equipe SAÍRA"])
    return subject, html, text


def build_password_changed_email(name: str, when: datetime) -> tuple[str, str, str]:
    first = _first_name(name)
    local = when.astimezone(BRAZIL_TIMEZONE).strftime("%d/%m/%Y às %H:%M")
    subject = "Sua senha do SAÍRA foi alterada"
    paragraphs = [
        f"Olá, {first}! A senha da sua conta no SAÍRA foi alterada em {local} (horário de Brasília).",
        "As sessões abertas em outros aparelhos foram encerradas.",
        "Se não foi você, avise o administrador do SAÍRA imediatamente.",
    ]
    html = _html([escape(p) for p in paragraphs])
    text = "\n\n".join([*paragraphs, "Equipe SAÍRA"])
    return subject, html, text


def _send(to: str, message: tuple[str, str, str]) -> bool:
    subject, html, text = message
    return email_service.send_email(
        to_addrs=[to],
        subject=subject,
        html_body=html,
        text_body=text,
        from_name=settings.ACCESS_EMAIL_FROM_NAME,
    )


def send_invite(user, link: str, invited_by: Optional[str]) -> bool:
    return _send(user.email, build_invite_email(user.name, link, invited_by))


def send_reset(user, link: str) -> bool:
    return _send(user.email, build_reset_email(user.name, link))


def send_password_changed(user, when: datetime) -> bool:
    return _send(user.email, build_password_changed_email(user.name, when))
