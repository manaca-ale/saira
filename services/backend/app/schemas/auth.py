from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.core.password_policy import MAX_LENGTH, MIN_LENGTH


class Token(BaseModel):
    access_token: str
    token_type: str
    # Senha provisória (definida pelo administrador): o frontend leva à troca.
    must_change_password: bool = False


class TokenData(BaseModel):
    email: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class PasswordTokenRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


class PasswordTokenInfo(BaseModel):
    purpose: str  # "invite" | "reset"
    name: str
    email: str
    expires_at: datetime


class SetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    password: str = Field(..., min_length=MIN_LENGTH, max_length=MAX_LENGTH)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=MAX_LENGTH)
    new_password: str = Field(..., min_length=MIN_LENGTH, max_length=MAX_LENGTH)


class MessageResponse(BaseModel):
    message: str
    email: str | None = None
