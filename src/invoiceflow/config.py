from functools import lru_cache
from typing import Literal
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "InvoiceFlow AI"
    APP_ENV: Literal["development", "test", "production"] = "development"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    JWT_SECRET: str = Field(
        default="dev-insecure-secret-key-must-be-changed-in-production-32-chars",
        min_length=32,
        description="Secret for JWT signature",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/invoiceflow",
        description="Async SQLAlchemy database connection URL",
    )
    REDIS_URL: str = "redis://localhost:6379/0"

    STORAGE_KIND: Literal["local", "s3"] = "local"
    LOCAL_STORAGE_DIR: str = "./data/storage"
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "invoiceflow-documents"
    S3_REGION: str = "us-east-1"

    LLM_PROVIDER: Literal["gemini", "openai"] = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.modelapi.vn/v1"
    OPENAI_MODEL_ID: str = "gpt-6.1-sol"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL_ID: str = "gemini-2.5-flash"
    MAX_PROVIDER_BUDGET_PER_DOC_USD: float = 0.05
    REQUEST_TIMEOUT_SECONDS: int = 30

    MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024
    MAX_DOCUMENT_PAGES: int = 50
    OCR_DPI: int = 150
    WORKER_CONCURRENCY: int = 4
    DEFAULT_PRICE_TOLERANCE_PCT: float = 2.0
    DEFAULT_QTY_TOLERANCE_PCT: float = 0.0
    DOCLING_TIMEOUT_SECONDS: int = 60

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if len(v.strip()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long.")
        return v.strip()

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.APP_ENV == "production":
            insecure_markers = ("dev-insecure", "change-this", "secret-key-32")
            if any(marker in self.JWT_SECRET.lower() for marker in insecure_markers):
                raise ValueError(
                    "In production (APP_ENV=production), a strong non-default JWT_SECRET is strictly required."
                )
            if self.STORAGE_KIND == "s3" and (
                self.S3_ACCESS_KEY == "minioadmin" or self.S3_SECRET_KEY == "minioadmin"
            ):
                raise ValueError(
                    "In production with S3 storage, default credentials 'minioadmin' are strictly forbidden."
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
