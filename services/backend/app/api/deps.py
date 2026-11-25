from typing import AsyncGenerator
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
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


async def get_current_user(
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

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Dependency para garantir que o usuário está ativo"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


# Bilhete de uso único do SSE. O EventSource do navegador não manda cabeçalho,
# então a URL precisa levar alguma credencial; em vez do JWT (que vale 24 h e
# ficava nos logs do proxy), vai um bilhete que vale uma conexão e vence em 60 s.
SSE_TICKET_PREFIX = "saira:sse:ticket:"
SSE_TICKET_TTL_SECONDS = 60


async def get_ticket_redis():
    """Cliente Redis dos bilhetes (o mesmo do fluxo Conecta)."""
    from app.api.v1.endpoints.conecta import get_redis_client

    return await get_redis_client()


async def get_current_user_from_sse_ticket(
    ticket: str = Query(..., min_length=16, max_length=128),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_ticket_redis),
) -> User:
    """Auth do SSE: troca o bilhete (criado em POST /notifications/stream-ticket) pelo usuário."""
    invalid_ticket = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired ticket",
    )

    key = f"{SSE_TICKET_PREFIX}{ticket}"
    raw = await redis.get(key)
    # Só quem apaga a chave usa o bilhete: duas conexões com o mesmo bilhete
    # não passam as duas.
    if not raw or not await redis.delete(key):
        raise invalid_ticket
    email = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        raise invalid_ticket

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return user
