from sqlalchemy import Column, Integer, String, Boolean, DateTime, text
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.timezone import now_brazil


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    secretaria = Column(String(100))
    cargo = Column(String(100))
    rpa = Column(String(10), index=True)
    # NULL = convite pendente: nenhuma senha serve no login até a pessoa
    # definir a dela pelo link (ver docs/specs/acesso-usuarios.md).
    password_hash = Column(String(255), nullable=True)
    # Senha definida por um administrador é provisória: o dono troca no 1º login.
    must_change_password = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Vai no JWT como "ver"; somar 1 derruba todas as sessões abertas.
    token_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
    password_changed_at = Column(DateTime(timezone=True), nullable=True)
    auth_provider = Column(String(50), nullable=False, default="local")
    external_subject = Column(String(255), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=now_brazil)
    updated_at = Column(DateTime(timezone=True), default=now_brazil, onupdate=now_brazil)

    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    @property
    def invite_pending(self) -> bool:
        return self.password_hash is None
