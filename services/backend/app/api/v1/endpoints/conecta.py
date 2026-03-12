import json
import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.redis import get_redis, init_redis
from app.core.security import create_access_token, get_password_hash
from app.models.user import User
from app.schemas.auth import Token
from app.schemas.conecta import (
    ConectaExchangeTicketRequest,
    ConectaLoginUrlResponse,
    ConectaLogoutUrlResponse,
    ConectaRevokeResponse,
)
from app.services.conecta_service import conecta_service
from app.core.timezone import now_brazil_naive

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)

STATE_KEY_PREFIX = "saira:conecta:state:"
TICKET_KEY_PREFIX = "saira:conecta:ticket:"


async def get_redis_client():
    try:
        return get_redis()
    except RuntimeError:
        return await init_redis()


def _sanitize_next(next_path: str | None) -> str:
    if not next_path:
        return "/dashboard"
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/dashboard"
    return next_path


def _frontend_callback_url(**params: str) -> str:
    callback_base = f"{settings.WEB_APP_URL.rstrip('/')}/login/callback"
    if not params:
        return callback_base
    return f"{callback_base}?{urlencode(params)}"


async def _upsert_user_from_conecta(
    db: AsyncSession,
    userinfo: dict[str, Any],
) -> User:
    subject = (userinfo.get("sub") or "").strip() or None
    email = (userinfo.get("email") or "").strip().lower()
    name = (userinfo.get("name") or userinfo.get("preferred_username") or "Usuario Conecta").strip()
    phone = (userinfo.get("phone_number") or "").strip() or None

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conecta userinfo response does not contain email",
        )

    conditions = [User.email == email]
    if subject:
        conditions.insert(0, User.external_subject == subject)

    result = await db.execute(select(User).where(or_(*conditions)))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            name=name,
            email=email,
            phone=phone,
            password_hash=get_password_hash(secrets.token_urlsafe(48)),
            auth_provider="conecta",
            external_subject=subject,
            is_active=True,
            last_login_at=now_brazil_naive(),
        )
        db.add(user)
    else:
        user.name = name
        user.email = email
        user.phone = phone
        user.auth_provider = "conecta"
        user.external_subject = subject
        user.is_active = True
        user.last_login_at = now_brazil_naive()

    await db.commit()
    await db.refresh(user)
    return user


@router.get("/login-url", response_model=ConectaLoginUrlResponse)
async def get_login_url(
    next_path: str = Query("/dashboard", alias="next"),
    redis=Depends(get_redis_client),
):
    """Retorna URL de login no Conecta Recife e state para CSRF."""
    conecta_service.ensure_enabled_and_configured()

    safe_next = _sanitize_next(next_path)
    state = secrets.token_urlsafe(32)
    state_data = {"next": safe_next}

    await redis.setex(
        f"{STATE_KEY_PREFIX}{state}",
        settings.CONECTA_STATE_TTL_SECONDS,
        json.dumps(state_data),
    )

    return ConectaLoginUrlResponse(
        authorization_url=conecta_service.build_authorization_url(state),
        state=state,
    )


@router.get("/callback")
async def conecta_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    redis=Depends(get_redis_client),
    db: AsyncSession = Depends(get_db),
):
    """Callback OIDC: troca code por token, sincroniza usuário e cria ticket temporário."""
    conecta_service.ensure_enabled_and_configured()

    if error:
        return RedirectResponse(
            _frontend_callback_url(error=error, message=error_description or "Authentication failed"),
            status_code=status.HTTP_302_FOUND,
        )

    if not code or not state:
        return RedirectResponse(
            _frontend_callback_url(error="invalid_callback", message="Missing code or state"),
            status_code=status.HTTP_302_FOUND,
        )

    state_key = f"{STATE_KEY_PREFIX}{state}"
    raw_state = await redis.get(state_key)
    await redis.delete(state_key)

    if not raw_state:
        return RedirectResponse(
            _frontend_callback_url(error="invalid_state", message="State expired or invalid"),
            status_code=status.HTTP_302_FOUND,
        )

    try:
        state_data = json.loads(raw_state)
    except json.JSONDecodeError:
        state_data = {}
    safe_next = _sanitize_next(state_data.get("next"))

    try:
        token_response = await conecta_service.exchange_code_for_token(code)
        access_token = token_response.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Conecta token response missing access_token",
            )

        userinfo = await conecta_service.fetch_userinfo(access_token)
        user = await _upsert_user_from_conecta(db, userinfo)
    except HTTPException as exc:
        return RedirectResponse(
            _frontend_callback_url(error="token_exchange_failed", message=str(exc.detail)),
            status_code=status.HTTP_302_FOUND,
        )

    local_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    ticket = secrets.token_urlsafe(32)
    await redis.setex(
        f"{TICKET_KEY_PREFIX}{ticket}",
        settings.CONECTA_TICKET_TTL_SECONDS,
        local_token,
    )

    return RedirectResponse(
        _frontend_callback_url(ticket=ticket, next=safe_next),
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/exchange-ticket", response_model=Token)
async def exchange_ticket(
    payload: ConectaExchangeTicketRequest,
    redis=Depends(get_redis_client),
):
    """Troca ticket temporário por JWT interno do SAIRA."""
    token = await redis.get(f"{TICKET_KEY_PREFIX}{payload.ticket}")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired ticket",
        )

    await redis.delete(f"{TICKET_KEY_PREFIX}{payload.ticket}")
    return Token(access_token=token, token_type="bearer")


@router.get("/logout-url", response_model=ConectaLogoutUrlResponse)
async def get_logout_url(
    redirect_uri: str | None = Query(None),
):
    """Retorna URL de logout no Conecta (SSO)."""
    conecta_service.ensure_enabled_and_configured()

    target_redirect = (
        redirect_uri
        or settings.CONECTA_POST_LOGOUT_REDIRECT_URI
        or settings.WEB_APP_URL
    )

    return ConectaLogoutUrlResponse(
        logout_url=conecta_service.build_logout_url(target_redirect),
    )


@router.post("/revoke-consent", response_model=ConectaRevokeResponse)
async def revoke_consent(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint para Carta de Serviços (Conecta Labs):
    valida token via introspect e revoga dados pessoais locais do usuário.
    """
    conecta_service.ensure_enabled_and_configured()

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    access_token = credentials.credentials
    introspection = await conecta_service.introspect_token(access_token)
    if not introspection.get("active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or invalid token",
        )

    subject = (introspection.get("sub") or "").strip() or None
    email = (introspection.get("email") or "").strip().lower() or None

    if not subject and not email:
        userinfo = await conecta_service.fetch_userinfo(access_token)
        subject = (userinfo.get("sub") or "").strip() or None
        email = (userinfo.get("email") or "").strip().lower() or None

    if not subject and not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to identify user from token",
        )

    filters = [User.auth_provider.in_(["conecta", "conecta_revoked"])]
    if subject and email:
        filters.append(or_(User.external_subject == subject, User.email == email))
    elif subject:
        filters.append(User.external_subject == subject)
    else:
        filters.append(User.email == email)

    result = await db.execute(select(User).where(*filters))
    user = result.scalar_one_or_none()
    if user is None:
        return ConectaRevokeResponse(
            status="no_user",
            message="No local user mapped for this Conecta token",
        )

    user.name = "Usuario Revogado"
    user.email = f"revogado+{user.id}@saira.local"
    user.phone = None
    user.secretaria = None
    user.cargo = None
    user.rpa = None
    user.password_hash = get_password_hash(secrets.token_urlsafe(48))
    user.external_subject = None
    user.auth_provider = "conecta_revoked"
    user.is_active = False
    user.updated_at = now_brazil_naive()

    await db.commit()

    return ConectaRevokeResponse(
        status="revoked",
        message="Dados pessoais revogados com sucesso",
    )
