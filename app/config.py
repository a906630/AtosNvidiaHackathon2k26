from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # NVIDIA NIM
    # On Brev with local NIM, API key is not required.
    nvidia_api_key: str = "no-key"
    nvidia_base_url: str = "http://localhost:8000/v1"
    nvidia_model: str = "meta/llama-3.3-70b-instruct"

    # Guardrails
    guardrails_enabled: bool = True
    guardrails_fail_closed: bool = False

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True
    app_title: str = "CZK - Centrum Zarzadzania Kryzysowego"


@lru_cache
def get_settings() -> Settings:
    return Settings()
