from pydantic import BaseModel, EmailStr, Field, computed_field
from datetime import datetime
from typing import Optional

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
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    secretaria: Optional[str] = Field(None, max_length=100)
    cargo: Optional[str] = Field(None, max_length=100)
    rpa: Optional[str] = Field(None, max_length=10)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)


class UserResponse(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def role(self) -> str:
        """Papel de acesso derivado do cargo ("admin" ou "operador")."""
        return role_from_cargo(self.cargo).value

    class Config:
        from_attributes = True


class UserInDB(UserResponse):
    password_hash: str
