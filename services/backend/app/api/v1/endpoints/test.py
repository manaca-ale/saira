from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.redis import get_redis
from app.models.user import User
from app.services.whatsapp_service import WhatsAppService

router = APIRouter()


class WhatsAppTestRequest(BaseModel):
    phone: str = Field(..., description="Phone number in raw or WhatsApp chatId format")
    message: str = Field(..., min_length=1, max_length=4096)


def _ensure_admin(current_user: User) -> None:
    cargo = (current_user.cargo or "").strip().lower()
    if cargo in {"administrador", "admin"}:
        return
    if current_user.email == "admin@saira.com":
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only administrators can access this endpoint",
    )


async def _enforce_rate_limit(user_id: int) -> None:
    try:
        redis = get_redis()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limiter unavailable",
        ) from exc
    key = f"ratelimit:whatsapp_test:user:{user_id}"
    limit = max(1, settings.WHATSAPP_TEST_RATE_LIMIT_PER_MINUTE)

    current = await redis.incr(key)
    if current == 1:
        await redis.expire(key, 60)

    if current > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for WhatsApp test endpoint",
        )


@router.post("/whatsapp")
async def send_whatsapp_test(
    payload: WhatsAppTestRequest,
    current_user: User = Depends(get_current_user),
):
    if not settings.ENABLE_WHATSAPP_TEST_ROUTE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    _ensure_admin(current_user)
    await _enforce_rate_limit(current_user.id)

    service = WhatsAppService()
    sent = service.send_message(payload.phone, payload.message)
    return {"success": sent, "provider": service.provider}
