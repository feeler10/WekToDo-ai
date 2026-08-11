from collections.abc import Callable
from datetime import datetime

from app.graph.state import TaskAgentState
from app.graph.task_delete_parser import TaskDeleteParser
from app.schemas.task_deletion import (
    TaskDeleteParseResult,
    TaskDeleteTargetScope,
)


async def parse_task_delete(
    state: TaskAgentState,
    *,
    parser: TaskDeleteParser | None,
    clock: Callable[[], datetime],
) -> dict[str, object]:
    try:
        if parser is None:
            reference = (state.get('task_reference') or '').strip()
            result = TaskDeleteParseResult.model_validate(
                {
                    'task_references': [reference] if reference else [],
                    'match_mode': 'EXACT',
                    'delete_all_matches': False,
                    'needs_clarification': not bool(reference),
                    'clarification_question': (
                        None if reference else '你想删除哪些任务？'
                    ),
                    'reason': '兼容单任务删除解析',
                }
            )
        else:
            result = TaskDeleteParseResult.model_validate(
                await parser.parse(
                    state.get('user_message', ''),
                    timezone=state.get('timezone', 'UTC'),
                    current_datetime=clock(),
                )
            )
    except Exception as exc:
        return {'error_message': f'删除条件解析失败：{exc}'}

    single_exact = (
        not result.needs_clarification
        and not result.delete_all_matches
        and len(result.task_references) == 1
        and not result.keywords
        and result.query.time_scope.value == 'UNSPECIFIED'
        and not result.query.statuses
        and not result.query.priorities
        and result.category is None
        and result.target_scope == TaskDeleteTargetScope.ALL_TASKS
    )
    return {
        'task_delete_parse_result': result.model_dump(mode='json'),
        'task_reference': (
            result.task_references[0] if single_exact else None
        ),
        'task_delete_route': (
            'clarification'
            if result.needs_clarification
            else ('single' if single_exact else 'batch')
        ),
        'final_response': (
            result.clarification_question
            if result.needs_clarification
            else None
        ),
        'error_message': None,
    }
