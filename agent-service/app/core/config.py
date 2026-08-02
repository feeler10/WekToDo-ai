from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.intent.enums import IntentClassifierProvider
from app.matching.factory import TaskMatcherProvider

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = 'WekToDo Agent Service'
    app_env: Literal['development', 'test', 'production'] = 'development'
    app_host: str = '127.0.0.1'
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_debug: bool = False
    redis_url: str = 'redis://127.0.0.1:6379/0'
    checkpoint_redis_url: str = 'redis://127.0.0.1:6379/0'
    llm_model: str = 'gpt-4.1-mini'
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_structured_output_method: Literal[
        'json_schema',
        'function_calling',
        'json_mode',
    ] = 'json_mode'
    task_parse_max_attempts: int = Field(default=3, ge=1, le=5)
    intent_classifier_provider: IntentClassifierProvider = (
        IntentClassifierProvider.LLM
    )
    intent_model_name: str = 'qwen-flash'
    task_matcher_provider: TaskMatcherProvider = (
        TaskMatcherProvider.KEYWORD
    )
    intent_model_temperature: float = Field(default=0, ge=0, le=2)
    intent_model_max_tokens: int = Field(default=200, ge=1)
    intent_model_enable_thinking: bool = False

    @field_validator('checkpoint_redis_url')
    @classmethod
    def require_checkpoint_database_zero(cls, value: str) -> str:
        database = urlparse(value).path.strip('/')
        if database not in ('', '0'):
            raise ValueError('checkpoint_redis_url must use Redis database 0')
        return value

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / '.env',
        env_file_encoding='utf-8',
        extra='ignore',
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
