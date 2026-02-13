from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://localhost:5174",
        "https://test-saira.manaca.tech"
    ]

    # S3/Storage
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_NAME: str = ""
    S3_REGION: str = "us-east-1"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # WhatsApp
    WHATSAPP_PROVIDER: str = "waha"
    WAHA_BASE_URL: str = "http://waha:3000"
    WAHA_API_KEY: str = ""
    WAHA_SESSION_NAME: str = "default"
    META_API_TOKEN: str = ""
    META_PHONE_ID: str = ""
    WEB_APP_URL: str = "http://localhost:3000"
    ENABLE_WHATSAPP_TEST_ROUTE: bool = False
    WHATSAPP_TEST_RATE_LIMIT_PER_MINUTE: int = 5

    # Application
    PROJECT_NAME: str = "SAIRA API"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Offender recurrence
    HIGH_RECURRENCE_THRESHOLD: int = 5

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
