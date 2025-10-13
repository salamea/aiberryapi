"""
Configuration management for AIBerry API
Uses pydantic-settings for environment-based configuration
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings with environment variable support"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_name: str = "aiberry-api"
    app_version: str = "1.0.0"
    environment: str = "dev"
    debug: bool = False

    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 2

    # Google Studio API
    google_api_key: str
    google_model: str = "gemini-1.5-flash"

    # Redis Configuration
    redis_host: str = "redis-service.aiberry.svc.cluster.local"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0
    redis_vector_index: str = "aiberry_vectors"

    # Memory Configuration
    redis_memory_host: str = "redis-service.aiberry.svc.cluster.local"
    redis_memory_port: int = 6379
    redis_memory_db: int = 1
    short_term_memory_ttl: int = 3600  # 1 hour
    long_term_memory_ttl: int = 2592000  # 30 days
    max_short_term_messages: int = 10

    # Embedding Service
    embedding_service_url: str = "http://aiberry-embeddings.aiberry.svc.cluster.local:8001"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Vector Search
    similarity_threshold: float = 0.7
    max_search_results: int = 10

    # LLM Configuration
    llm_temperature: float = 0.7
    llm_max_tokens: int = 2048
    llm_timeout: int = 60

    # Guardrails
    guardrails_enabled: bool = True
    guardrails_config_path: str = "./config/guardrails"
    max_input_length: int = 2000
    max_output_length: int = 4000

    # Document Processing
    max_file_size_mb: int = 10
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Security
    allowed_origins: list[str] = ["http://fend.aisolution.com"]
    api_key_header: str = "X-API-Key"
    whitelisted_ips: list[str] = ["170.45.23.4"]

    # Monitoring
    enable_metrics: bool = True
    metrics_port: int = 9090

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    def get_redis_url(self) -> str:
        """Get Redis connection URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def get_redis_memory_url(self) -> str:
        """Get Redis memory connection URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_memory_host}:{self.redis_memory_port}/{self.redis_memory_db}"
        return f"redis://{self.redis_memory_host}:{self.redis_memory_port}/{self.redis_memory_db}"
