"""Application Configuration Module."""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Application & Environment
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    service_name: str = Field(default="incident-triage-api", alias="SERVICE_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    debug: bool = Field(default=False, alias="DEBUG")

    # Worker & Queue
    worker_concurrency: int = Field(default=4, alias="WORKER_CONCURRENCY")
    queue_name: str = Field(default="incident_triage_queue", alias="QUEUE_NAME")
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")
    redis_db: int = Field(default=0, alias="REDIS_DB")

    # Vector Database
    vector_db_type: str = Field(default="chroma", alias="VECTOR_DB_TYPE")
    chroma_host: str = Field(default="localhost", alias="CHROMA_HOST")
    chroma_port: int = Field(default=8001, alias="CHROMA_PORT")
    chroma_persist_dir: str = Field(default="./data/chroma", alias="CHROMA_PERSIST_DIR")

    # OpenTelemetry & Tracing
    otel_service_name: str = Field(default="incident-triage-assistant", alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: str = Field(default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    enable_tracing: bool = Field(default=True, alias="ENABLE_TRACING")

    # Prometheus Metrics
    prometheus_metrics_path: str = Field(default="/metrics", alias="PROMETHEUS_METRICS_PATH")

    # LLM Settings
    llm_provider: str = Field(default="stub", alias="LLM_PROVIDER")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_api_key: Optional[str] = Field(default=None, alias="LLM_API_KEY")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=1024, alias="LLM_MAX_TOKENS")

    # Stub Model (for testing & offline load evaluation)
    stub_model_latency_ms: int = Field(default=150, alias="STUB_MODEL_LATENCY_MS")
    stub_model_failure_rate: float = Field(default=0.0, alias="STUB_MODEL_FAILURE_RATE")

    # Prompt Version Management
    active_prompt_version: str = Field(default="v1.1.0", alias="ACTIVE_PROMPT_VERSION")
    prompts_dir: str = Field(default="./prompts", alias="PROMPTS_DIR")

    # Rate Limiting
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_requests_per_minute: int = Field(default=60, alias="RATE_LIMIT_REQUESTS_PER_MINUTE")
    rate_limit_burst: int = Field(default=10, alias="RATE_LIMIT_BURST")

    # Caching
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_ttl_seconds: int = Field(default=3600, alias="CACHE_TTL_SECONDS")

    # Cost Tracking
    cost_per_1k_prompt_tokens: float = Field(default=0.00015, alias="COST_PER_1K_PROMPT_TOKENS")
    cost_per_1k_completion_tokens: float = Field(default=0.00060, alias="COST_PER_1K_COMPLETION_TOKENS")

    # Security & Guardrails
    enable_injection_defense: bool = Field(default=True, alias="ENABLE_INJECTION_DEFENSE")
    enable_output_filtering: bool = Field(default=True, alias="ENABLE_OUTPUT_FILTERING")
    enable_toxicity_check: bool = Field(default=True, alias="ENABLE_TOXICITY_CHECK")
    max_alert_text_length: int = Field(default=4096, alias="MAX_ALERT_TEXT_LENGTH")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
