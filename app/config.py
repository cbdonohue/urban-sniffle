from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment (and optional `.env`)."""

    aeroapi_api_key: str
    aeroapi_base_url: str = "https://aeroapi.flightaware.com/aeroapi"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
