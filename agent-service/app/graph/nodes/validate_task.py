from typing import Any

from pydantic import ValidationError

from app.graph.parser import ParsedTaskDraft
from app.graph.state import TaskAgentState
from app.schemas.task import TaskCreate


def validate_task(state: TaskAgentState) -> dict[str, Any]:
    raw_task = state.get('task_draft')
    user_id = state.get('user_id')
    if not user_id:
        return {
            'validation_passed': False,
            'missing_fields': ['user_id'],
            'validation_errors': ['user_id is required'],
            'error_message': 'Task validation failed',
        }
    if raw_task is None:
        return {
            'validation_passed': False,
            'missing_fields': ['task_draft'],
            'validation_errors': ['task_draft is required'],
            'error_message': 'Task validation failed',
        }

    try:
        draft = ParsedTaskDraft.model_validate(raw_task)
        task_create = TaskCreate(
            user_id=user_id,
            title=draft.title,
            description=draft.description,
            category=draft.category,
            deadline=draft.deadline,
            estimated_minutes=draft.estimated_minutes,
            user_priority=state.get('user_priority'),
            priority_reason=draft.priority_reason,
            is_ai_generated=True,
        )
    except ValidationError as exc:
        errors = exc.errors()
        missing_fields = [
            str(error['loc'][0])
            for error in errors
            if error['type'] == 'missing'
        ]
        return {
            'validation_passed': False,
            'missing_fields': missing_fields,
            'validation_errors': [error['msg'] for error in errors],
            'error_message': 'Task validation failed',
        }

    return {
        'task_draft': draft.model_dump(mode='json'),
        'parsed_task': task_create.model_dump(mode='json'),
        'priority_factors': {
            'deadline_score': draft.deadline_score,
            'semantic_importance': draft.semantic_importance,
            'impact_score': draft.impact_score,
            'workload_risk_score': draft.workload_risk_score,
            'dependency_score': draft.dependency_score,
        },
        'priority_reason': draft.priority_reason,
        'validation_passed': True,
        'missing_fields': [],
        'validation_errors': [],
        'error_message': None,
    }
