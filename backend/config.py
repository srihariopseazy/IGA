import os
from functools import lru_cache
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AnyHttpUrl, validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    # App
    APP_NAME: str = "IGA Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    SECRET_KEY: str = "changeme-secret-key-32chars-minimum"
    ENCRYPTION_KEY: str = "changeme-encryption-key-32chars!!"  # 32-byte base64-encoded key for AES-256
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql://iga:iga@localhost:5432/iga"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_SESSION_DB: int = 1
    REDIS_CACHE_DB: int = 2

    # RabbitMQ / Celery
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672/"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/3"

    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_SECRET_KEY: str = "changeme-jwt-secret-key-32chars!!"

    # OAuth2
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_CLIENT_ID: Optional[str] = None
    MICROSOFT_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_TENANT_ID: Optional[str] = None

    # SAML
    SAML_SP_ENTITY_ID: str = "https://iga.example.com"
    SAML_IDP_METADATA_URL: Optional[str] = None

    # Email
    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@iga.example.com"
    SMTP_TLS: bool = True

    # SMS / Twilio
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    TWILIO_FROM_NUMBER: Optional[str] = None

    # MinIO / S3
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "iga-artifacts"
    MINIO_SECURE: bool = False

    # LDAP
    LDAP_SERVER: Optional[str] = None
    LDAP_PORT: int = 389
    LDAP_USE_SSL: bool = False
    LDAP_BIND_DN: Optional[str] = None
    LDAP_BIND_PASSWORD: Optional[str] = None
    LDAP_BASE_DN: Optional[str] = None
    LDAP_USER_BASE_DN: Optional[str] = None
    LDAP_GROUP_BASE_DN: Optional[str] = None

    # OPA
    OPA_URL: str = "http://localhost:8181"

    # Vault (HashiCorp)
    VAULT_URL: Optional[str] = None
    VAULT_TOKEN: Optional[str] = None
    VAULT_MOUNT_POINT: str = "secret"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000

    # Security
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 30
    SESSION_TIMEOUT_MINUTES: int = 60
    PASSWORD_MIN_LENGTH: int = 12
    MFA_OTP_VALIDITY_SECONDS: int = 300
    MAGIC_LINK_EXPIRE_MINUTES: int = 15

    # Provisioning
    PROVISIONING_MAX_RETRIES: int = 3
    PROVISIONING_RETRY_DELAY_SECONDS: int = 60

    # Certification
    CERTIFICATION_DEFAULT_DEADLINE_DAYS: int = 30
    CERTIFICATION_ESCALATION_DAYS: int = 7

    # Monitoring
    PROMETHEUS_ENABLED: bool = True
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    OTEL_SERVICE_NAME: str = "iga-backend"

    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    # IP Reputation
    IPINFO_TOKEN: Optional[str] = None

    # SoD
    SOD_SCAN_INTERVAL_HOURS: int = 24

    # Risk scoring weights
    RISK_WEIGHT_SOD_VIOLATION: float = 30.0
    RISK_WEIGHT_ANOMALOUS_LOGIN: float = 20.0
    RISK_WEIGHT_OVER_PROVISIONED: float = 15.0
    RISK_WEIGHT_CERT_FAILURE: float = 20.0
    RISK_WEIGHT_PEER_DEVIATION: float = 15.0

    @validator("CORS_ORIGINS", pre=True)
    def parse_cors(cls, v):
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
