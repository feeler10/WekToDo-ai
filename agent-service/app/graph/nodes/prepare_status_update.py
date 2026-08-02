from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from app.graph.state import TaskAgentState
from app.schemas.audit import PendingAction
from app.schemas.task import Task, TaskStatus, TaskStatusUpdate, utc_now
from app.services.task_state import validate_status_transition


def prepare_status_update(state: TaskAgentState) -> dict[str, object]:
    try:
        task = Task.model_validate(state.get('selected_task'))
        target = TaskStatus(state['target_status'])
        if task.status == target:
            return {
                'updated_task': task.model_dump(mode='json'),
                'final_response': f'Task is already {target.value}: {task.title}',
                'error_message': None,
            }
        confirmed_reopen = task.status == TaskStatus.DONE and target == TaskStatus.DOING
        validate_status_transition(
            task.status,
            target,
            confirmed_reopen=confirmed_reopen,
        )
        payload = TaskStatusUpdate(
            user_id=task.user_id,
            current_status=task.status,
            target_status=target,
            expected_version=task.version,
            confirmed_reopen=confirmed_reopen,
        )
        confirmation_round = state.get('confirmation_round', 0) + 1
        request_id = state.get('request_id') or state['thread_id']
        identity = ':'.join(
            (
                task.user_id,
                state['thread_id'],
                request_id,
                'update_task_status',
                str(confirmation_round),
            )
        )
        now = utc_now()
        pending = PendingAction(
            id=str(uuid5(NAMESPACE_URL, identity)),
            user_id=task.user_id,
            thread_id=state['thread_id'],
            action_type='update_task_status',
            target_id=task.id,
            payload=payload.model_dump(mode='json'),
            idempotency_key=f'update_task_status:{request_id}',
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    except Exception as exc:
        return {'error_message': f'Could not prepare status update: {exc}'}

    return {
        'pending_action': pending.model_dump(mode='json'),
        'confirmation_round': confirmation_round,
        'confirmation_status': 'pending',
        'review_action': None,
        'error_message': None,
    }
