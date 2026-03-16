from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ENABLE_LOCAL_LOGIN: bool = True
    ENABLE_CONECTA_LOGIN: bool = False

    # Conecta Recife (OIDC)
    CONECTA_ENV: str = "test"  # test | prod
    CONECTA_BASE_URL_TEST: str = "https://loginteste.recife.pe.gov.br"
    CONECTA_BASE_URL_PROD: str = "https://login.recife.pe.gov.br"
    CONECTA_REALM: str = "recife"
    CONECTA_CLIENT_ID: str = ""
    CONECTA_CLIENT_SECRET: str = ""
    CONECTA_REDIRECT_URI: str = ""
    CONECTA_POST_LOGOUT_REDIRECT_URI: str = ""
    CONECTA_SCOPE: str = "openid profile email"
    CONECTA_STATE_TTL_SECONDS: int = 600
    CONECTA_TICKET_TTL_SECONDS: int = 120
    CONECTA_HTTP_TIMEOUT_SECONDS: int = 15

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

    # Geocodificação
    NOMINATIM_BASE_URL: str = "https://nominatim.openstreetmap.org"
    NOMINATIM_USER_AGENT: str = "saira-dashboard/1.0 (contato@saira.com)"
    GEOCODING_COUNTRYCODES: str = "br"
    # viewbox: lon_min,lat_max,lon_max,lat_min  (Região Metropolitana do Recife)
    GEOCODING_VIEWBOX: str = "-35.10,-7.80,-34.70,-8.20"
    GEOCODING_TIMEOUT_SECONDS: float = 5.0

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
