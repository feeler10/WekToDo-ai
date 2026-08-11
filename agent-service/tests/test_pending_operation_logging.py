import logging
from datetime import datetime, timezone

from app.services.pending_operation_logging import log_pending_operation_event


def test_pending_operation_log_is_structured_and_omits_content(caplog) -> None:
    logger = logging.getLogger('tests.pending-operation')
    state = {
        'request_id': 'request-1',
        'user_id': 'user-1',
        'thread_id': 'thread-1',
        'user_message': '不要记录这段用户原话',
        'task_draft': {'title': '不要记录这个标题'},
    }

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_pending_operation_event(
            logger,
            state=state,
            operation_type='task_update',
            event='prepared',
            round_number=2,
            task_id='task-1',
            expected_version=3,
            reason='needs_field_value',
            next_node='finalize_turn',
            expires_at=datetime(2026, 8, 11, 9, tzinfo=timezone.utc),
        )

    message = caplog.messages[-1]
    assert 'event=prepared' in message
    assert 'operation_type=task_update' in message
    assert 'request_id=request-1' in message
    assert 'thread_id=thread-1' in message
    assert 'task_id=task-1' in message
    assert 'expected_version=3' in message
    assert '不要记录这段用户原话' not in message
    assert '不要记录这个标题' not in message
