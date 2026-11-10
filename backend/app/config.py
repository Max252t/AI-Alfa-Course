from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://alfa:change_me@localhost:5432/alfa"
    id_hash_salt: str = "change_me"

    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_model: str = "yandexgpt-lite"

    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dim: int = 768
    relevance_threshold: float = 0.35

    platform_base_url: str = "https://alfa-course.example"
    default_tz: str = "Europe/Moscow"
    tax_calendar_path: str = "/app/data/tax_calendar.yaml"


@lru_cache
def get_settings() -> Settings:
    return Settings()
