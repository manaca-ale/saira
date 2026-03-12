from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.timezone import now_brazil_naive


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20))
    secretaria = Column(String(100))
    cargo = Column(String(100))
    rpa = Column(String(10), index=True)
    password_hash = Column(String(255), nullable=False)
    auth_provider = Column(String(50), nullable=False, default="local")
    external_subject = Column(String(255), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=now_brazil_naive)
    updated_at = Column(DateTime, default=now_brazil_naive, onupdate=now_brazil_naive)

    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
