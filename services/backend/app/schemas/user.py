from pydantic import BaseModel, EmailStr, Field, computed_field
from datetime import datetime
from typing import Optional

from app.core.password_policy import MAX_LENGTH, MIN_LENGTH
from app.core.roles import role_from_cargo


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)
    secretaria: Optional[str] = Field(None, max_length=100)
    cargo: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    is_active: bool = True


class UserCreate(UserBase):
    # Sem senha (o normal): o usuário nasce com convite pendente e recebe o
    # link por e-mail. Com senha: ela é provisória e o dono troca no 1º login.
    password: Optional[str] = Field(None, min_length=MIN_LENGTH, max_length=MAX_LENGTH)
    send_invite: bool = True


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    secretaria: Optional[str] = Field(None, max_length=100)
    cargo: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=MIN_LENGTH, max_length=MAX_LENGTH)


class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None
    must_change_password: bool = False
    # Convite pendente: ainda não há senha (a pessoa não usou o link).
    invite_pending: bool = False

    @computed_field
    @property
    def role(self) -> str:
        """Papel de acesso derivado do cargo ("admin" ou "operador")."""
        return role_from_cargo(self.cargo).value

    class Config:
        from_attributes = True


class UserWithInviteResponse(UserResponse):
    # None = nenhum convite pedido; False = convite gravado, mas o e-mail falhou.
    invite_email_sent: Optional[bool] = None


class UserInDB(UserResponse):
    password_hash: Optional[str]
