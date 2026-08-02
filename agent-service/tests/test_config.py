import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_checkpoint_redis_url_requires_database_zero() -> None:
    with pytest.raises(ValidationError, match='must use Redis database 0'):
        Settings(
            app_env='test',
            checkpoint_redis_url='redis://127.0.0.1:6379/15',
        )


def test_structured_output_method_defaults_to_json_mode() -> None:
    settings = Settings(app_env='test', _env_file=None)

    assert settings.llm_structured_output_method == 'json_mode'


@pytest.mark.parametrize(
    'method',
    ['json_schema', 'function_calling', 'json_mode'],
)
def test_structured_output_method_accepts_supported_values(method: str) -> None:
    settings = Settings(
        app_env='test',
        llm_structured_output_method=method,
        _env_file=None,
    )

    assert settings.llm_structured_output_method == method


def test_structured_output_method_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            llm_structured_output_method='xml',
            _env_file=None,
        )
