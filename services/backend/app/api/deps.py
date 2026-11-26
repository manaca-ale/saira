from typing import AsyncGenerator
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.core.roles import Role, role_from_cargo
from app.models.user import User
from app.schemas.user import UserResponse

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency para obter sessão do banco de dados"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


PASSWORD_CHANGE_REQUIRED = "password_change_required"

# Com senha provisória, o usuário logado só alcança estas rotas até trocar a senha.
PASSWORD_CHANGE_ALLOWED_SUFFIXES = ("/auth/me", "/auth/password/change")


def token_version_matches(payload: dict, user: User) -> bool:
    """O JWT leva a versão de sessão ("ver"; ausente = 0). Trocar a senha soma 1
    em users.token_version e todos os tokens anteriores deixam de valer."""
    try:
        return int(payload.get("ver", 0)) == int(getattr(user, "token_version", 0) or 0)
    except (TypeError, ValueError):
        return False


def enforce_password_change(user: User, path: str) -> None:
    if getattr(user, "must_change_password", False) and not path.endswith(PASSWORD_CHANGE_ALLOWED_SUFFIXES):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PASSWORD_CHANGE_REQUIRED)


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency para obter o usuário atual autenticado"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception

    # Buscar usuário no banco
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not token_version_matches(payload, user):
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )

    enforce_password_change(user, request.url.path)

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency para garantir que o usuário está ativo"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def require_role(*roles: Role):
    """Dependency que só deixa passar usuário logado com um dos papéis dados.

    O papel vem do `cargo` (ver app.core.roles). Quem não tem o papel recebe 403.
    """
    allowed = frozenset(roles)

    async def _require_role(current_user: User = Depends(get_current_user)) -> User:
        if role_from_cargo(current_user.cargo) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso restrito a: " + ", ".join(sorted(r.value for r in allowed)),
            )
        return current_user

    _require_role.required_roles = allowed
    return _require_role


# Gestão de usuários, configuração de câmera e custos: só administrador.
require_admin = require_role(Role.ADMIN)


async def get_current_user_from_query(
    token: str = Query(..., alias="token"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Auth via query param for SSE (EventSource doesn't support custom headers)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not token_version_matches(payload, user):
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    enforce_password_change(user, "")

    return user
