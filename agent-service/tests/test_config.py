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


def test_pending_context_ttl_has_bounded_default() -> None:
    settings = Settings(app_env='test', _env_file=None)

    assert settings.pending_context_ttl_seconds == 900
    assert settings.active_task_context_ttl_seconds == 1800

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            pending_context_ttl_seconds=30,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            active_task_context_ttl_seconds=30,
            _env_file=None,
        )


def test_task_draft_clarification_rounds_have_bounded_default() -> None:
    settings = Settings(app_env='test', _env_file=None)

    assert settings.task_draft_clarification_max_rounds == 4
    assert settings.task_update_clarification_max_rounds == 4

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            task_draft_clarification_max_rounds=0,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            task_draft_clarification_max_rounds=9,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            task_update_clarification_max_rounds=0,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            task_update_clarification_max_rounds=9,
            _env_file=None,
        )


def test_conversation_history_limit_has_bounded_default() -> None:
    settings = Settings(app_env='test', _env_file=None)

    assert settings.conversation_history_max_messages == 200

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            conversation_history_max_messages=19,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            conversation_history_max_messages=1001,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            conversation_history_max_messages=201,
            _env_file=None,
        )
