from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = 'WekToDo Agent Service'
    app_env: Literal['development', 'test', 'production'] = 'development'
    app_host: str = '127.0.0.1'
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_debug: bool = False

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
