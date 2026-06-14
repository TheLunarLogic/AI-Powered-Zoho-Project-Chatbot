"""Application configuration loaded from environment variables."""

import functools
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """
    Central configuration loaded from environment variables and an optional .env file.

    Required fields have no defaults — the application will raise a ValidationError
    at startup if any of them are missing from the environment.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # -------------------------------------------------------------------------
    # Zoho OAuth — required
    # -------------------------------------------------------------------------
    zoho_client_id: str
    zoho_client_secret: str = Field(..., repr=False)
    zoho_redirect_uri: str

    # -------------------------------------------------------------------------
    # Zoho API base URLs — have sensible defaults
    # -------------------------------------------------------------------------
    zoho_base_url: str = "https://projectsapi.zoho.in/restapi"
    zoho_accounts_url: str = "https://accounts.zoho.in"

    # -------------------------------------------------------------------------
    # Database — required
    # -------------------------------------------------------------------------
    database_url: str

    # -------------------------------------------------------------------------
    # Security — required
    # -------------------------------------------------------------------------
    secret_key: str = Field(..., repr=False)

    # -------------------------------------------------------------------------
    # LLM provider — defaults to AWS Bedrock
    # -------------------------------------------------------------------------
    llm_provider: str = "bedrock"

    # AWS Bedrock
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.amazon.nova-lite-v1:0"

    # AWS credentials — optional; omit when running on AWS with an IAM role
    aws_access_key_id: Optional[str] = Field(default=None, repr=False)
    aws_secret_access_key: Optional[str] = Field(default=None, repr=False)
    aws_session_token: Optional[str] = Field(default=None, repr=False)

    # Google Gemini — optional; only required when llm_provider == "gemini"
    google_api_key: Optional[str] = Field(default=None, repr=False)
    gemini_model_id: Optional[str] = None

    # -------------------------------------------------------------------------
    # Frontend URL — used for post-auth redirects
    # -------------------------------------------------------------------------
    frontend_url: str = "http://localhost:3000"
    session_cookie_name: str = "zpc_session"
    session_ttl_hours: int = 8

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------
    log_level: str = "INFO"


@functools.lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the cached singleton Config instance.

    The instance is created once on first call and reused for the lifetime
    of the process.  Use ``get_config.cache_clear()`` in tests to reset it.
    """
    return Config()
