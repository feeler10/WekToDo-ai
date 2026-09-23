from datetime import timedelta
import logging
from uuid import NAMESPACE_URL, uuid5

from app.graph.state import TaskAgentState
from app.graph.subtask_planner import SubtaskPlanner
from app.repositories.base import TaskRepository
from app.schemas.audit import PendingAction
from app.schemas.subtask import (
    SubtaskBatchCreate,
    SubtaskPlan,
    SubtaskPlanDraft,
)
from app.schemas.task import Task, utc_now
from app.services.subtask_plan import validate_subtask_plan
from app.tools.task_tools import create_subtasks_batch
from app.services.error_mapping import error_state
from app.services.observability import ObservabilityService, execute_observed_tool


logger = logging.getLogger(__name__)


async def load_decomposition_context(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        selected = Task.model_validate(state.get('selected_task'))
        parent = await repository.get(
            user_id=state['user_id'],
            task_id=selected.id,
        )
        if parent is None:
            raise ValueError('父任务不存在或不属于当前用户')
        if parent.parent_id is not None:
            raise ValueError('当前版本不支持继续拆解子任务')
        if parent.status.value == 'CANCELLED':
            raise ValueError('已取消的父任务不能拆解')
        children = await repository.list_children(
            user_id=state['user_id'],
            parent_id=parent.id,
        )
    except Exception as exc:
        return {'error_message': f'加载任务拆解上下文失败：{exc}'}
    return {
        'selected_task': parent.model_dump(mode='json'),
        'parent_task': parent.model_dump(mode='json'),
        'existing_subtasks': [
            child.model_dump(mode='json') for child in children
        ],
        'decomposition_message': (
            state.get('decomposition_message') or state.get('user_message')
        ),
        'error_message': None,
    }


async def generate_subtask_plan(
    state: TaskAgentState,
    *,
    planner: SubtaskPlanner | None,
) -> dict[str, object]:
    if planner is None:
        return {'error_message': 'Subtask planner is not configured'}
    try:
        parent = Task.model_validate(
            state.get('parent_task') or state.get('selected_task')
        )
        children = [
            Task.model_validate(item)
            for item in state.get('existing_subtasks', [])
        ]
        draft = await planner.generate(
            parent=parent,
            user_message=(
                state.get('decomposition_message')
                or state.get('user_message', '')
            ),
            existing_children=children,
            timezone=state.get('timezone', 'UTC'),
            feedback=state.get('regeneration_feedback'),
        )
    except Exception as exc:
        return {'error_message': f'生成任务拆解方案失败：{exc}'}
    return {
        'subtask_plan_draft': SubtaskPlanDraft.model_validate(draft).model_dump(
            mode='json'
        ),
        'subtask_plan': None,
        'regeneration_feedback': None,
        'error_message': None,
    }


def validate_generated_subtask_plan(
    state: TaskAgentState,
) -> dict[str, object]:
    try:
        parent = Task.model_validate(
            state.get('parent_task') or state.get('selected_task')
        )
        draft = SubtaskPlanDraft.model_validate(
            state.get('subtask_plan_draft')
        )
        children = [
            Task.model_validate(item)
            for item in state.get('existing_subtasks', [])
        ]
        plan = validate_subtask_plan(
            parent=parent,
            draft=draft,
            existing_children=children,
        )
    except Exception as exc:
        return {'error_message': f'任务拆解方案校验失败：{exc}'}
    return {
        'subtask_plan': plan.model_dump(mode='json'),
        'error_message': None,
    }


def prepare_subtask_confirmation(
    state: TaskAgentState,
) -> dict[str, object]:
    try:
        plan = SubtaskPlan.model_validate(state.get('subtask_plan'))
        batch = SubtaskBatchCreate(
            user_id=state['user_id'],
            parent_task_id=plan.parent_task_id,
            expected_parent_version=plan.parent_version,
            items=plan.items,
        )
        confirmation_round = state.get('confirmation_round', 0) + 1
        request_id = state.get('request_id') or state['thread_id']
        identity = ':'.join(
            (
                state['user_id'],
                state['thread_id'],
                request_id,
                'create_subtasks_batch',
                str(confirmation_round),
            )
        )
        now = utc_now()
        pending = PendingAction(
            id=str(uuid5(NAMESPACE_URL, identity)),
            user_id=state['user_id'],
            thread_id=state['thread_id'],
            action_type='create_subtasks_batch',
            target_id=plan.parent_task_id,
            payload=batch.model_dump(mode='json'),
            idempotency_key=f'create_subtasks_batch:{request_id}',
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    except Exception as exc:
        return {'error_message': f'准备任务拆解确认失败：{exc}'}
    return {
        'pending_action': pending.model_dump(mode='json'),
        'confirmation_round': confirmation_round,
        'confirmation_status': 'pending',
        'review_action': None,
        'error_message': None,
    }


async def execute_create_subtasks_batch(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    observability: ObservabilityService | None = None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        confirmed = pending.confirmation_status == 'approved'
        result = await execute_observed_tool(
            observability,
            state=state,
            tool_name='create_subtasks_batch',
            input_payload={
                **pending.payload,
                'subtask_count': len(pending.payload.get('items', [])),
            },
            confirmed=confirmed,
            idempotency_key=pending.idempotency_key,
            action_id=pending.id,
            operation=lambda: create_subtasks_batch(
                repository=repository,
                batch_input=pending.payload,
                idempotency_key=pending.idempotency_key,
                confirmed=confirmed,
            ),
        )
    except Exception as exc:
        return error_state(exc, trace_id=state.get('trace_id'))
    logger.info(
        'tool=create_subtasks_batch user_id=%s thread_id=%s action_id=%s '
        'parent_task_id=%s subtask_count=%s confirmed=true replayed=%s',
        state.get('user_id'),
        state.get('thread_id'),
        pending.id,
        result.parent_task.id,
        len(result.subtasks),
        result.replayed,
    )
    return {
        'parent_task': result.parent_task.model_dump(mode='json'),
        'selected_task': result.parent_task.model_dump(mode='json'),
        'created_subtasks': [
            task.model_dump(mode='json') for task in result.subtasks
        ],
        'final_response': (
            f'已为“{result.parent_task.title}”创建 '
            f'{len(result.subtasks)} 个子任务。'
        ),
        'error_message': None,
    }
