"""Tokens de uso único dos links de convite e de recuperação de senha.

Só o SHA-256 do token fica no banco; o token em si só existe no e-mail.
Ver docs/specs/acesso-usuarios.md.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.core.database import Base
from app.core.timezone import now_brazil


class UserActionToken(Base):
    __tablename__ = "user_action_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(20), nullable=False)  # "invite" | "reset"
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now_brazil)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_ip = Column(String(45), nullable=True)
