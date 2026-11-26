"""Links de uso único (convite e recuperação de senha) e troca de senha.

O token aleatório só existe no link do e-mail; o banco guarda o SHA-256.
Regras e motivos em docs/specs/acesso-usuarios.md.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.user import User
from app.models.user_action_token import UserActionToken

PURPOSE_INVITE = "invite"
PURPOSE_RESET = "reset"
PURPOSES = (PURPOSE_INVITE, PURPOSE_RESET)

TOKEN_INVALID = "token_invalid"
TOKEN_EXPIRED = "token_expired"
TOKEN_USED = "token_used"


class TokenError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class TokenCheck:
    token: UserActionToken
    user: User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    # Postgres (timestamptz) devolve com fuso; SQLite dos testes, sem. Sem fuso = UTC.
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def ttl_for(purpose: str) -> timedelta:
    if purpose == PURPOSE_INVITE:
        return timedelta(hours=settings.ACCESS_INVITE_TTL_HOURS)
    if purpose == PURPOSE_RESET:
        return timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES)
    raise ValueError(f"propósito desconhecido: {purpose}")


def public_base_url() -> str:
    return (settings.APP_PUBLIC_URL or settings.REPORT_DASHBOARD_URL).rstrip("/")


def password_link(raw_token: str) -> str:
    # O token vai no fragmento (#): o navegador não o manda ao servidor, então
    # ele não aparece em log de acesso nem no cabeçalho Referer.
    return f"{public_base_url()}/definir-senha#token={raw_token}"


async def issue_token(
    db: AsyncSession,
    user: User,
    purpose: str,
    *,
    created_by: Optional[User] = None,
    request_ip: Optional[str] = None,
) -> str:
    """Cria um link novo e apaga os pendentes do mesmo usuário e propósito."""
    if purpose not in PURPOSES:
        raise ValueError(f"propósito desconhecido: {purpose}")
    await db.execute(
        delete(UserActionToken).where(
            and_(
                UserActionToken.user_id == user.id,
                UserActionToken.purpose == purpose,
                UserActionToken.used_at.is_(None),
            )
        )
    )
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        UserActionToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=now + ttl_for(purpose),
            created_at=now,
            created_by_user_id=getattr(created_by, "id", None),
            request_ip=(request_ip or None) and request_ip[:45],
        )
    )
    await db.flush()
    return raw


async def check_token(db: AsyncSession, raw: str) -> TokenCheck:
    """Confere o link sem consumir. Levanta TokenError com o motivo."""
    if not raw or len(raw) > 256:
        raise TokenError(TOKEN_INVALID)
    result = await db.execute(
        select(UserActionToken, User)
        .join(User, User.id == UserActionToken.user_id)
        .where(UserActionToken.token_hash == hash_token(raw))
    )
    row = result.first()
    if row is None:
        raise TokenError(TOKEN_INVALID)
    token, user = row
    if token.purpose not in PURPOSES or not user.is_active:
        raise TokenError(TOKEN_INVALID)
    if token.used_at is not None:
        raise TokenError(TOKEN_USED)
    if _aware(token.expires_at) <= utcnow():
        raise TokenError(TOKEN_EXPIRED)
    return TokenCheck(token=token, user=user)


def apply_new_password(user: User, new_password: str) -> None:
    """Grava a senha escolhida pelo próprio dono e derruba as sessões antigas."""
    user.password_hash = get_password_hash(new_password)
    user.must_change_password = False
    user.token_version = int(user.token_version or 0) + 1
    user.password_changed_at = utcnow()


async def drop_pending_tokens(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        delete(UserActionToken).where(
            and_(UserActionToken.user_id == user_id, UserActionToken.used_at.is_(None))
        )
    )


async def consume_token_and_set_password(db: AsyncSession, raw: str, new_password: str) -> TokenCheck:
    """Consome o link (uso único) e define a senha. Levanta TokenError."""
    check = await check_token(db, raw)
    # UPDATE condicional: dois cliques ao mesmo tempo não consomem o link duas vezes.
    result = await db.execute(
        update(UserActionToken)
        .where(and_(UserActionToken.id == check.token.id, UserActionToken.used_at.is_(None)))
        .values(used_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise TokenError(TOKEN_USED)
    apply_new_password(check.user, new_password)
    await drop_pending_tokens(db, check.user.id)
    await db.flush()
    return check


def revoke_password_for_invite(user: User) -> None:
    """Convite para usuário existente: a senha atual (provisória, escolhida por
    outra pessoa) deixa de valer e as sessões abertas caem."""
    user.password_hash = None
    user.must_change_password = False
    user.token_version = int(user.token_version or 0) + 1
