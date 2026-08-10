from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from app.graph.state import TaskAgentState
from app.schemas.audit import PendingAction
from app.schemas.task import Task, TaskUpdate, utc_now
from app.services.task_response import format_task_update_preview


def prepare_task_update(state: TaskAgentState) -> dict[str, object]:
    try:
        task = Task.model_validate(state.get('selected_task'))
        update = TaskUpdate.model_validate(state.get('task_update'))
        confirmation_round = state.get('confirmation_round', 0) + 1
        request_id = state.get('request_id') or state['thread_id']
        identity = ':'.join(
            (
                task.user_id,
                state['thread_id'],
                request_id,
                'update_task',
                str(confirmation_round),
            )
        )
        now = utc_now()
        pending = PendingAction(
            id=str(uuid5(NAMESPACE_URL, identity)),
            user_id=task.user_id,
            thread_id=state['thread_id'],
            action_type='update_task',
            target_id=task.id,
            payload=update.model_dump(mode='json', exclude_unset=True),
            idempotency_key=f'update_task:{request_id}',
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    except Exception as exc:
        return {'error_message': f'Could not prepare task update: {exc}'}
    return {
        'pending_action': pending.model_dump(mode='json'),
        'confirmation_round': confirmation_round,
        'confirmation_status': 'pending',
        'review_action': None,
        'final_response': format_task_update_preview(
            task,
            update,
            timezone_name=state.get('timezone', 'UTC'),
        ),
        'error_message': None,
    }
