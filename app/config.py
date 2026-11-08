"""Validated environment configuration; invalid credentials fail at startup."""

from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    HOST: str = "0.0.0.0"
    PORT: int = Field(default=8000, ge=1, le=65535)
    WEBHOOK_SECRET: SecretStr
    GITHUB_TOKEN: SecretStr
    LLM_PROVIDER: str = "openai"
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: SecretStr | None = None
    LLM_MODEL_NAME: str = "gpt-4o"
    LLM_TEMPERATURE: float = Field(default=0.2, ge=0, le=2)
    HTTP_TIMEOUT: float = Field(default=30, gt=0)
    LLM_TIMEOUT: float = Field(default=120, gt=0)
    MAX_WEBHOOK_BYTES: int = Field(default=2_000_000, gt=0)
    MAX_DIFF_BYTES: int = Field(default=100_000, gt=0)
    MAX_CONCURRENT_REVIEWS: int = Field(default=4, ge=1)
    AUTO_REVIEW: bool = True

    @field_validator("WEBHOOK_SECRET", "GITHUB_TOKEN", "LLM_API_KEY")
    @classmethod
    def nonempty_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("Secrets must not be empty")
        return value

    @field_validator("HOST", "LLM_PROVIDER", "LLM_MODEL_NAME")
    @classmethod
    def nonempty_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def provider_defaults(self) -> Self:
        self.LLM_PROVIDER = self.LLM_PROVIDER.lower()
        if self.LLM_BASE_URL is None:
            if self.LLM_PROVIDER == "ollama":
                self.LLM_BASE_URL = "http://localhost:11434/v1"
            elif self.LLM_PROVIDER == "openai":
                self.LLM_BASE_URL = "https://api.openai.com/v1"
            else:
                raise ValueError("LLM_BASE_URL is required for this provider")
        url = urlsplit(self.LLM_BASE_URL)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "LLM_BASE_URL must be an HTTP(S) URL without credentials, query or fragment"
            )
        if self.LLM_API_KEY is None:
            if self.LLM_PROVIDER == "ollama":
                self.LLM_API_KEY = SecretStr("ollama")
            else:
                raise ValueError("LLM_API_KEY is required for this provider")
        return self


settings = Settings()
