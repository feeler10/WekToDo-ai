from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from app.graph.state import TaskAgentState
from app.schemas.audit import PendingAction
from app.schemas.task import TaskCreate, utc_now


def prepare_confirmation(state: TaskAgentState) -> dict[str, object]:
    try:
        payload = TaskCreate.model_validate(
            {
                **(state.get('parsed_task') or {}),
                'ai_priority': state.get('ai_priority'),
                'urgency_score': state.get('urgency_score'),
                'priority_reason': state.get('priority_reason'),
                'user_priority': state.get('user_priority'),
                'is_ai_generated': True,
            }
        )
        confirmation_round = state.get('confirmation_round', 0) + 1
        request_id = state.get('request_id') or state['thread_id']
        identity = ':'.join(
            (
                state['user_id'],
                state['thread_id'],
                request_id,
                str(confirmation_round),
            )
        )
        now = utc_now()
        pending = PendingAction(
            id=str(uuid5(NAMESPACE_URL, identity)),
            user_id=state['user_id'],
            thread_id=state['thread_id'],
            action_type='create_task',
            payload=payload.model_dump(mode='json'),
            idempotency_key=f'create_task:{request_id}',
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    except Exception as exc:
        return {'error_message': f'Could not prepare confirmation: {exc}'}

    return {
        'pending_action': pending.model_dump(mode='json'),
        'confirmation_round': confirmation_round,
        'confirmation_status': 'pending',
        'review_action': None,
        'error_message': None,
    }
