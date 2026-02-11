"""Application configuration using Pydantic Settings."""
from functools import lru_cache
from typing import Any, Dict, List, Optional, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="OpenAI API Convertor", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Server
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8000, alias="PORT")

    # AWS
    aws_region: str = Field(default="us-west-2", alias="AWS_REGION")
    aws_access_key_id: Optional[str] = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")
    bedrock_endpoint_url: Optional[str] = Field(default=None, alias="BEDROCK_ENDPOINT_URL")

    # DynamoDB
    dynamodb_endpoint_url: Optional[str] = Field(default=None, alias="DYNAMODB_ENDPOINT_URL")
    dynamodb_api_keys_table: str = Field(
        default="openai-proxy-api-keys", alias="DYNAMODB_API_KEYS_TABLE"
    )
    dynamodb_usage_table: str = Field(
        default="openai-proxy-usage", alias="DYNAMODB_USAGE_TABLE"
    )
    dynamodb_model_mapping_table: str = Field(
        default="openai-proxy-model-mapping", alias="DYNAMODB_MODEL_MAPPING_TABLE"
    )
    dynamodb_pricing_table: str = Field(
        default="openai-proxy-pricing", alias="DYNAMODB_PRICING_TABLE"
    )
    dynamodb_usage_stats_table: str = Field(
        default="openai-proxy-usage-stats", alias="DYNAMODB_USAGE_STATS_TABLE"
    )

    # Authentication
    api_key_header: str = Field(default="x-api-key", alias="API_KEY_HEADER")
    require_api_key: bool = Field(default=True, alias="REQUIRE_API_KEY")
    master_api_key: Optional[str] = Field(default=None, alias="MASTER_API_KEY")

    # Rate Limiting
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_requests: int = Field(default=100, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=60, alias="RATE_LIMIT_WINDOW")

    # Model Mapping
    default_model_mapping: Dict[str, str] = Field(
        default={
            "claude-opus-4-5": "global.anthropic.claude-opus-4-5-20251101-v1:0",
            "claude-opus-4-5-20251101": "global.anthropic.claude-opus-4-5-20251101-v1:0",
            "claude-opus-4-6": "global.anthropic.claude-opus-4-6-v1",
            "claude-sonnet-4-5": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "claude-sonnet-4-5-20250929": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
            "claude-haiku-4-5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
            "claude-haiku-4-5-20251001": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
            "claude-3-5-haiku": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "claude-3-5-haiku-20241022": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        },
        alias="DEFAULT_MODEL_MAPPING",
    )

    # Features
    enable_vision: bool = Field(default=True, alias="ENABLE_VISION")
    enable_tool_use: bool = Field(default=True, alias="ENABLE_TOOL_USE")
    enable_extended_thinking: bool = Field(default=True, alias="ENABLE_EXTENDED_THINKING")

    # Timeouts
    bedrock_timeout: int = Field(default=300, alias="BEDROCK_TIMEOUT")
    streaming_timeout: int = Field(default=600, alias="STREAMING_TIMEOUT")

    # CORS
    cors_origins: Union[str, List[str]] = Field(default=["*"], alias="CORS_ORIGINS")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in valid:
            raise ValueError(f"Log level must be one of {valid}")
        return v


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
