import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal


PendingOperationEvent = Literal[
    'prepared',
    'resumed',
    'cancelled',
    'replaced',
    'expired',
    'stale',
    'max_rounds',
]
PendingOperationType = Literal['task_create', 'task_update']


def log_pending_operation_event(
    logger: logging.Logger,
    *,
    state: Mapping[str, Any],
    operation_type: PendingOperationType,
    event: PendingOperationEvent,
    round_number: int | None = None,
    missing_fields: Sequence[str] | None = None,
    task_id: str | None = None,
    expected_version: int | None = None,
    reason: str | None = None,
    next_node: str | None = None,
    expires_at: datetime | None = None,
) -> None:
    """Log bounded pending-state metadata without user or task content."""
    logger.info(
        'pending_operation event=%s operation_type=%s request_id=%s '
        'user_id=%s thread_id=%s round=%s missing_fields=%s task_id=%s '
        'expected_version=%s reason=%s next_node=%s expires_at=%s',
        event,
        operation_type,
        state.get('request_id'),
        state.get('user_id'),
        state.get('thread_id'),
        round_number,
        list(missing_fields or []),
        task_id,
        expected_version,
        reason,
        next_node,
        expires_at.isoformat() if expires_at is not None else None,
    )
