from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.schemas.task import Task, TaskStatus, TaskStatusUpdate, utc_now
from app.tools.task_tools import update_task_status_with_rollup


def prepare_task_restore(state: TaskAgentState) -> dict[str, object]:
    try:
        task = Task.model_validate(state.get('selected_task'))
        if task.status != TaskStatus.CANCELLED:
            raise ValueError('Only cancelled tasks require restoration')
        payload = TaskStatusUpdate(
            user_id=task.user_id,
            current_status=TaskStatus.CANCELLED,
            target_status=TaskStatus.TODO,
            expected_version=task.version,
            confirmed_restore=True,
        )
        confirmation_round = state.get('confirmation_round', 0) + 1
        request_id = state.get('request_id') or state['thread_id']
        identity = ':'.join(
            (
                task.user_id,
                state['thread_id'],
                request_id,
                'restore_task',
                str(confirmation_round),
            )
        )
        now = utc_now()
        pending = PendingAction(
            id=str(uuid5(NAMESPACE_URL, identity)),
            user_id=task.user_id,
            thread_id=state['thread_id'],
            action_type='restore_task',
            target_id=task.id,
            payload=payload.model_dump(mode='json'),
            idempotency_key=f'restore_task:{request_id}',
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    except Exception as exc:
        return {'error_message': f'Could not prepare task restoration: {exc}'}
    return {
        'pending_action': pending.model_dump(mode='json'),
        'confirmation_round': confirmation_round,
        'confirmation_status': 'pending',
        'review_action': None,
        'final_response': (
            f'任务“{task.title}”已被取消。需要先恢复为待办，'
            '才能继续当前操作。是否恢复？'
        ),
        'error_message': None,
    }


async def execute_task_restore(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        payload = TaskStatusUpdate.model_validate(pending.payload)
        if pending.target_id is None:
            raise ValueError('Restore target_id is required')
        result = await update_task_status_with_rollup(
            repository=repository,
            user_id=payload.user_id,
            task_id=pending.target_id,
            target_status=TaskStatus.TODO,
            expected_version=payload.expected_version,
            confirmed_restore=True,
            idempotency_key=pending.idempotency_key,
            confirmed=pending.confirmation_status == 'approved',
        )
    except Exception as exc:
        return {'error_message': f'恢复任务失败：{exc}'}
    return {
        'selected_task': result.task.model_dump(mode='json'),
        'updated_task': result.task.model_dump(mode='json'),
        'parent_task': (
            result.parent_task.model_dump(mode='json')
            if result.parent_task is not None
            else None
        ),
        'pending_action': None,
        'confirmation_status': None,
        'review_action': None,
        'restored_from_cancelled': True,
        'final_response': None,
        'error_message': None,
    }
