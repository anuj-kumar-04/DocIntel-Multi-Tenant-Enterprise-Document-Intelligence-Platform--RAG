from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET_PREFIX = "dev-docintel-"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    APP_NAME: str = "DocIntel"
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = True

    # Security
    SECRET_KEY: str = Field(default="dev-docintel-super-secret-key-32-chars-long-minimum-jwt")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ACCOUNT_LOCKOUT_MAX_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_SECONDS: int = 900
    ENABLE_SWAGGER_IN_PROD: bool = False

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://docintel_admin:docintel_secure_pass@localhost:5432/docintel"
    )
    DATABASE_URL_SYNC: str = Field(
        default="postgresql+psycopg2://docintel_admin:docintel_secure_pass@localhost:5432/docintel"
    )
    POSTGRES_USER: str = "docintel_admin"
    POSTGRES_PASSWORD: str = "docintel_secure_pass"
    POSTGRES_DB: str = "docintel"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # S3 / MinIO
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_BUCKET_NAME: str = "docintel-documents"
    S3_REGION: str = "us-east-1"

    # LLM Router & Models
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    DEFAULT_LLM_MODEL: str = "groq/qwen/qwen3.8-27b"
    FALLBACK_LLM_MODEL: str = "gemini/gemini-3.5-flash-lite"

    # Embedding & Re-ranking
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIMENSION: int = 384
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"

    # Retrieval Pipeline
    RETRIEVAL_VERSION: Literal["v1", "v2", "v3"] = "v3"
    DENSE_TOP_K: int = 20
    SPARSE_TOP_K: int = 20
    FUSION_TOP_N: int = 30
    FINAL_RERANK_TOP_K: int = 6
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_THRESHOLD: float = 0.97

    # Multi-tenancy & Limits
    DEFAULT_MONTHLY_TOKEN_BUDGET: int = 1_000_000
    MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB

    # Telemetry & Observability
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_BASE_URL: str = "https://us.cloud.langfuse.com"
    LANGFUSE_HOST: str = "https://us.cloud.langfuse.com"
    PROMETHEUS_METRICS_ENABLED: bool = True

    # CORS
    FRONTEND_URL: str = "http://localhost:3000"

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Fail fast if insecure development defaults are left active in production."""
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY.startswith(_DEV_SECRET_PREFIX) or len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "Production deployment requires a strong SECRET_KEY (>= 32 random chars)."
                )
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production.")
        return self


settings = Settings()
