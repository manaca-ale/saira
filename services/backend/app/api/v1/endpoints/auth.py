import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from app.api.deps import get_db, get_current_user
from app.core import rate_limit
from app.core.client_ip import client_ip
from app.core.password_policy import password_problem
from app.core.security import verify_password, create_user_access_token
from app.core.config import settings
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    MessageResponse,
    PasswordTokenInfo,
    PasswordTokenRequest,
    SetPasswordRequest,
    Token,
)
from app.schemas.user import UserResponse
from app.core.timezone import now_brazil
from app.services import access_email, access_service

logger = logging.getLogger(__name__)

router = APIRouter()

FORGOT_MESSAGE = (
    "Se houver uma conta ativa com esse e-mail, enviamos um link para criar uma senha nova. "
    "Confira a caixa de entrada e o spam."
)


def _client_ip(request: Request) -> str:
    # Não é request.client: o uvicorn põe ali o endereço que o visitante escreve
    # no X-Forwarded-For (ver app/core/client_ip.py).
    return client_ip(request)


def _login_key(email: str) -> str:
    return f"login:fail:{email.strip().lower()}"


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """Login e geração de token JWT"""
    if not settings.ENABLE_LOCAL_LOGIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Local login is disabled for this environment",
        )

    # Limite de tentativas por e-mail: janela curta, não bloqueio permanente
    # (senão qualquer um trancaria a conta de outra pessoa).
    key = _login_key(form_data.username)
    if await rate_limit.count(key) >= settings.LOGIN_MAX_FAILURES_PER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Muitas tentativas de login. Tente de novo em "
                f"{settings.LOGIN_FAILURE_WINDOW_MINUTES} minutos ou use \"Esqueceu a senha?\"."
            ),
        )

    # Buscar usuário por email
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    # Convite pendente (sem senha) cai aqui também: mesma resposta de senha errada.
    if not user or not verify_password(form_data.password, user.password_hash):
        await rate_limit.hit(
            key, settings.LOGIN_MAX_FAILURES_PER_EMAIL, settings.LOGIN_FAILURE_WINDOW_MINUTES * 60
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )

    await rate_limit.reset(key)

    # Atualizar last_login_at
    user.last_login_at = now_brazil()

    return {
        "access_token": create_user_access_token(user),
        "token_type": "bearer",
        "must_change_password": bool(user.must_change_password),
    }


# POST /auth/register foi removido em 25/11/2026: era aberto (qualquer um se
# cadastrava já ativo). Usuário novo só por POST /users/, que exige administrador.


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Retorna dados do usuário logado"""
    return current_user


# ── Senha: convite, recuperação e troca (docs/specs/acesso-usuarios.md) ──
# Rotas públicas respondem 400 (nunca 401) quando o link não serve: o frontend
# trata 401 como sessão vencida e mandaria a pessoa para o login.


def _token_error(exc: access_service.TokenError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code)


def _reject_weak(password: str, email: str) -> None:
    problem = password_problem(password, email)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)


@router.post("/password/forgot", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Manda o link de recuperação. Responde igual exista ou não a conta."""
    hour = 3600
    if not await rate_limit.hit(f"forgot:ip:{_client_ip(request)}", settings.PASSWORD_FORGOT_MAX_PER_IP_HOUR, hour):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitos pedidos deste endereço. Tente de novo em uma hora.",
        )
    email = body.email.strip().lower()
    # Passou do limite por e-mail: a resposta é a mesma, só não sai e-mail
    # (um 429 aqui contaria que alguém pediu para esse endereço).
    if not await rate_limit.hit(f"forgot:email:{email}", settings.PASSWORD_FORGOT_MAX_PER_EMAIL_HOUR, hour):
        logger.warning("forgot_password: limite por e-mail atingido")
        return {"message": FORGOT_MESSAGE}

    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()
    if user is not None and user.is_active:
        raw = await access_service.issue_token(
            db, user, access_service.PURPOSE_RESET, request_ip=_client_ip(request)
        )
        await db.commit()
        # Envio depois da resposta: o tempo de resposta não revela se a conta existe.
        background.add_task(access_email.send_reset, user, access_service.password_link(raw))
    return {"message": FORGOT_MESSAGE}


@router.post("/password/token", response_model=PasswordTokenInfo)
async def password_token_info(body: PasswordTokenRequest, db: AsyncSession = Depends(get_db)):
    """Confere o link (sem consumir) para a tela mostrar o nome ou o erro."""
    try:
        check = await access_service.check_token(db, body.token)
    except access_service.TokenError as exc:
        raise _token_error(exc)
    return {
        "purpose": check.token.purpose,
        "name": check.user.name,
        "email": check.user.email,
        "expires_at": check.token.expires_at,
    }


@router.post("/password/set", response_model=MessageResponse)
async def set_password(
    body: SetPasswordRequest,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Define a senha pelo link do convite ou da recuperação (uso único)."""
    try:
        check = await access_service.check_token(db, body.token)
        _reject_weak(body.password, check.user.email)
        check = await access_service.consume_token_and_set_password(db, body.token, body.password)
    except access_service.TokenError as exc:
        raise _token_error(exc)
    await db.commit()
    user = check.user
    if check.token.purpose == access_service.PURPOSE_RESET:
        background.add_task(access_email.send_password_changed, user, user.password_changed_at)
    await rate_limit.reset(_login_key(user.email))
    return {"message": "Senha criada. Entre com o seu e-mail e a senha nova.", "email": user.email}


@router.post("/password/change", response_model=Token)
async def change_password(
    body: ChangePasswordRequest,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Troca a senha de quem está logado (inclusive a provisória). Devolve um
    token novo: a troca derruba as sessões anteriores."""
    if not verify_password(body.current_password, current_user.password_hash):
        # 400, não 401: 401 o frontend trata como sessão vencida.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta.")
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A senha nova precisa ser diferente da atual.",
        )
    _reject_weak(body.new_password, current_user.email)
    access_service.apply_new_password(current_user, body.new_password)
    await access_service.drop_pending_tokens(db, current_user.id)
    await db.commit()
    background.add_task(access_email.send_password_changed, current_user, current_user.password_changed_at)
    return {
        "access_token": create_user_access_token(current_user),
        "token_type": "bearer",
        "must_change_password": False,
    }
