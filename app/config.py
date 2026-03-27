from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    aeroapi_api_key: str
    aeroapi_base_url: AnyHttpUrl = "https://aeroapi.flightaware.com/aeroapi"


def get_settings() -> Settings:
    return Settings()
