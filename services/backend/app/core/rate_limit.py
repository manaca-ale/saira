"""Contador de janela fixa para limitar pedidos (login, "esqueci minha senha").

Usa o Redis do backend (INCR + EXPIRE). Sem Redis (testes, ou Redis fora do
ar) cai num contador em memória do processo: limita menos entre réplicas, mas
não derruba o login.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_memory: dict[str, tuple[int, float]] = {}


def _redis_or_none():
    try:
        from app.core.redis import get_redis

        return get_redis()
    except Exception:
        return None


async def _incr(key: str, window_seconds: int) -> int:
    redis = _redis_or_none()
    if redis is not None:
        try:
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, window_seconds)
            return int(count)
        except Exception:
            logger.warning("rate_limit: Redis indisponível, usando contador em memória")
    now = time.monotonic()
    count, reset_at = _memory.get(key, (0, now + window_seconds))
    if now >= reset_at:
        count, reset_at = 0, now + window_seconds
    count += 1
    _memory[key] = (count, reset_at)
    return count


async def _get(key: str) -> int:
    redis = _redis_or_none()
    if redis is not None:
        try:
            value = await redis.get(key)
            return int(value or 0)
        except Exception:
            logger.warning("rate_limit: Redis indisponível, usando contador em memória")
    count, reset_at = _memory.get(key, (0, 0.0))
    return count if time.monotonic() < reset_at else 0


async def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Conta um pedido. Devolve True se ainda está dentro do limite."""
    return await _incr(f"ratelimit:{key}", window_seconds) <= limit


async def count(key: str) -> int:
    return await _get(f"ratelimit:{key}")


async def reset(key: str) -> None:
    full = f"ratelimit:{key}"
    _memory.pop(full, None)
    redis = _redis_or_none()
    if redis is not None:
        try:
            await redis.delete(full)
        except Exception:
            pass


def clear_memory() -> None:
    """Só para testes."""
    _memory.clear()
