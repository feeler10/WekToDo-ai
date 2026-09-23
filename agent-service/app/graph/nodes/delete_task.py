import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from app.graph.state import TaskAgentState
from app.repositories.base import TaskRepository
from app.repositories.exceptions import (
    TaskDeletionBlockedError,
    TaskNotFoundError,
    TaskRepositoryConcurrencyError,
    TaskRepositoryConsistencyError,
    TaskVersionConflictError,
)
from app.schemas.audit import PendingAction
from app.schemas.task import Task, utc_now
from app.schemas.task import TaskQuery
from app.schemas.task_deletion import (
    PendingTaskDeleteSelection,
    TaskDelete,
    TaskDeleteBatch,
    TaskDeleteBatchItem,
    TaskDeleteParseResult,
    TaskDeleteTargetScope,
)
from app.intent.enums import IntentType, TimeScope
from app.intent.models import IntentResult
from app.matching.base import TaskMatcher
from app.matching.models import MatchKind, TaskMatchResult
from app.services.task_response import (
    STATUS_LABELS,
    format_multiple_matches_response,
)
from app.services.task_query_plan import build_task_query_plan, task_query_from_plan
from app.tools.task_tools import delete_task, delete_tasks_batch
from app.services.error_mapping import error_state
from app.services.observability import ObservabilityService, execute_observed_tool

logger = logging.getLogger(__name__)


async def prepare_task_delete_batch(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    task_matcher: TaskMatcher,
    clock: Callable[[], datetime],
    pending_ttl: timedelta,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        parsed = TaskDeleteParseResult.model_validate(
            state.get('task_delete_parse_result')
        )
        all_tasks = await _load_all_user_tasks(repository, state['user_id'])
        resolved_parent_id = state.get('resolved_delete_parent_id')
        resolved_references = dict(
            state.get('resolved_delete_references') or {}
        )
        parent_task: Task | None = None
        if parsed.target_scope == TaskDeleteTargetScope.DIRECT_CHILDREN:
            if resolved_parent_id:
                parent_task = next(
                    (
                        task
                        for task in all_tasks
                        if task.id == resolved_parent_id
                        and task.parent_id is None
                    ),
                    None,
                )
                if parent_task is None:
                    return {
                        'pending_task_delete_selection': None,
                        'candidate_tasks': [],
                        'final_response': '已选择的父任务已发生变化，请重新发起删除。',
                        'error_message': None,
                    }
            else:
                parent_match = task_matcher.match(
                    reference=parsed.parent_reference or '',
                    user_id=state['user_id'],
                    tasks=[task for task in all_tasks if task.parent_id is None],
                )
                if not parent_match.tasks:
                    return {
                        'candidate_tasks': [],
                        'pending_task_delete_selection': None,
                        'final_response': (
                            f'没有找到父任务“{parsed.parent_reference}”，未生成删除计划。'
                        ),
                        'error_message': None,
                    }
                if len(parent_match.tasks) > 1:
                    return _prepare_delete_selection(
                        state,
                        parsed=parsed,
                        selection_kind='parent',
                        reference=parsed.parent_reference or '父任务',
                        candidates=parent_match.tasks,
                        resolved_parent_id=None,
                        resolved_references=resolved_references,
                        clock=clock,
                        pending_ttl=pending_ttl,
                    )
                parent_task = parent_match.tasks[0]
                resolved_parent_id = parent_task.id
        query_intent = parsed.query
        if query_intent.time_scope == TimeScope.UNSPECIFIED:
            query_intent = query_intent.model_copy(
                update={'time_scope': TimeScope.ALL}
            )
        query_plan = build_task_query_plan(
            intent_result=IntentResult(
                intent=IntentType.QUERY_TASKS,
                confidence=1,
                reason='删除计划确定性查询',
                query=query_intent,
            ),
            user_id=state['user_id'],
            timezone_name=state.get('timezone', 'UTC'),
            now=clock(),
        )
        query = task_query_from_plan(query_plan, limit=100).model_copy(
            update={'category': parsed.category}
        )
        candidates = await _load_query_tasks(repository, query)
        if parent_task is not None:
            candidates = [
                task for task in candidates if task.parent_id == parent_task.id
            ]
        if parsed.task_references:
            referenced_ids: set[str] = set()
            missing_references: list[str] = []
            ambiguous_references: list[tuple[str, list[Task]]] = []
            for reference in parsed.task_references:
                resolved_task_id = resolved_references.get(reference)
                if resolved_task_id is not None:
                    resolved_task = next(
                        (
                            task
                            for task in candidates
                            if task.id == resolved_task_id
                        ),
                        None,
                    )
                    if resolved_task is None:
                        missing_references.append(reference)
                    else:
                        referenced_ids.add(resolved_task.id)
                    continue
                matched = task_matcher.match(
                    reference=reference,
                    user_id=state['user_id'],
                    tasks=candidates,
                )
                matched_tasks = _explicit_reference_matches(matched)
                if not matched_tasks:
                    missing_references.append(reference)
                elif len(matched_tasks) > 1:
                    ambiguous_references.append(
                        (reference, matched_tasks)
                    )
                else:
                    referenced_ids.add(matched_tasks[0].id)
            if missing_references:
                ambiguous_text = (
                    '；另外这些引用存在多个候选：'
                    + '、'.join(
                        reference
                        for reference, _tasks in ambiguous_references
                    )
                    if ambiguous_references
                    else ''
                )
                return {
                    'candidate_tasks': [],
                    'pending_task_delete_selection': None,
                    'deletion_tasks': [],
                    'final_response': (
                        '以下待删除任务没有找到：'
                        + '、'.join(missing_references)
                        + ambiguous_text
                        + '。未生成删除计划，也不会部分删除。'
                    ),
                    'error_message': None,
                }
            if ambiguous_references:
                reference, ambiguous_tasks = ambiguous_references[0]
                return _prepare_delete_selection(
                    state,
                    parsed=parsed,
                    selection_kind='task_reference',
                    reference=reference,
                    candidates=ambiguous_tasks,
                    resolved_parent_id=resolved_parent_id,
                    resolved_references=resolved_references,
                    clock=clock,
                    pending_ttl=pending_ttl,
                )
            if len(referenced_ids) != len(parsed.task_references):
                return {
                    'candidate_tasks': [],
                    'pending_task_delete_selection': None,
                    'deletion_tasks': [],
                    'final_response': (
                        '多个任务引用指向了同一个任务，无法确定你的删除范围。'
                        '请使用任务 ID 分别指定，未生成删除计划。'
                    ),
                    'error_message': None,
                }
            candidates = [
                task for task in candidates if task.id in referenced_ids
            ]
        if parsed.keywords:
            keywords = [_normalize_text(value) for value in parsed.keywords]
            candidates = [
                task
                for task in candidates
                if all(
                    keyword in _task_search_text(task)
                    for keyword in keywords
                )
            ]
        if len(candidates) > 50:
            return {
                'deletion_tasks': [],
                'final_response': (
                    f'删除条件匹配到 {len(candidates)} 个任务，超过单批 50 个的安全上限。'
                    '请缩小时间、状态、分类或关键词范围。'
                ),
                'error_message': None,
            }
        if not candidates:
            return {
                'deletion_tasks': [],
                'final_response': '没有找到符合删除条件的任务。',
                'error_message': None,
            }

        target_ids = {task.id for task in candidates}
        blockers: list[str] = []
        for task in candidates:
            children = await repository.list_children(
                user_id=state['user_id'],
                parent_id=task.id,
            )
            if children:
                blockers.append(
                    f'“{task.title}”有 {len(children)} 个直接子任务'
                )
        for task in all_tasks:
            if task.id in target_ids:
                continue
            depended = target_ids.intersection(task.depends_on_task_ids)
            if depended:
                blockers.append(f'“{task.title}”依赖本批次中的任务')
        serialized = [task.model_dump(mode='json') for task in candidates]
        if blockers:
            return {
                'deletion_tasks': serialized,
                'final_response': _format_delete_preview(
                    candidates,
                    timezone=state.get('timezone', 'UTC'),
                    blockers=blockers,
                ),
                'error_message': None,
            }

        batch = TaskDeleteBatch(
            user_id=state['user_id'],
            items=[
                TaskDeleteBatchItem(
                    task_id=task.id,
                    expected_version=task.version,
                )
                for task in candidates
            ],
        )
        confirmation_round = state.get('confirmation_round', 0) + 1
        request_id = state.get('request_id') or state['thread_id']
        identity = ':'.join(
            (
                state['user_id'],
                state['thread_id'],
                request_id,
                'delete_tasks_batch',
                str(confirmation_round),
            )
        )
        now = utc_now()
        pending = PendingAction(
            id=str(uuid5(NAMESPACE_URL, identity)),
            user_id=state['user_id'],
            thread_id=state['thread_id'],
            action_type='delete_tasks_batch',
            target_id=None,
            payload=batch.model_dump(mode='json'),
            idempotency_key=f'delete_tasks_batch:{request_id}',
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    except Exception as exc:
        return {'error_message': f'生成删除计划失败：{exc}'}
    return {
        'deletion_tasks': serialized,
        'candidate_tasks': [],
        'pending_task_delete_selection': None,
        'resolved_delete_parent_id': resolved_parent_id,
        'resolved_delete_references': resolved_references,
        'parent_task': (
            parent_task.model_dump(mode='json')
            if parent_task is not None
            else None
        ),
        'pending_action': pending.model_dump(mode='json'),
        'confirmation_round': confirmation_round,
        'confirmation_status': 'pending',
        'review_action': None,
        'final_response': _format_delete_preview(
            candidates,
            timezone=state.get('timezone', 'UTC'),
        ),
        'error_message': None,
    }


def _prepare_delete_selection(
    state: TaskAgentState,
    *,
    parsed: TaskDeleteParseResult,
    selection_kind: str,
    reference: str,
    candidates: list[Task],
    resolved_parent_id: str | None,
    resolved_references: dict[str, str],
    clock: Callable[[], datetime],
    pending_ttl: timedelta,
) -> dict[str, object]:
    now = clock()
    pending = PendingTaskDeleteSelection(
        user_id=state['user_id'],
        thread_id=state['thread_id'],
        parse_result=parsed,
        selection_kind=selection_kind,
        current_reference=reference,
        candidate_task_ids=[task.id for task in candidates],
        candidate_versions={task.id: task.version for task in candidates},
        resolved_parent_id=resolved_parent_id,
        resolved_references=resolved_references,
        created_at=now,
        expires_at=now + pending_ttl,
    )
    role = '父任务' if selection_kind == 'parent' else '待删除任务'
    return {
        'pending_task_delete_selection': pending.model_dump(mode='json'),
        'candidate_tasks': [
            task.model_dump(mode='json') for task in candidates
        ],
        'deletion_tasks': [],
        'final_response': format_multiple_matches_response(
            reference=reference,
            tasks=candidates,
            timezone_name=state.get('timezone', 'UTC'),
            operation_label=f'选择作为{role}',
        ),
        'error_message': None,
    }


async def prepare_task_delete(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    try:
        task = Task.model_validate(state.get('selected_task'))
        direct_children = await repository.list_children(
            user_id=task.user_id,
            parent_id=task.id,
        )
        if direct_children:
            return {
                'final_response': (
                    f'任务“{task.title}”仍有 {len(direct_children)} 个直接子任务，'
                    '不能直接删除。请先处理这些子任务。'
                ),
                'error_message': None,
            }

        parent: Task | None = None
        if task.parent_id is not None:
            parent = await repository.get(
                user_id=task.user_id,
                task_id=task.parent_id,
            )
            if parent is None:
                raise TaskRepositoryConsistencyError(
                    'Child task references a missing parent'
                )
            siblings = await repository.list_children(
                user_id=task.user_id,
                parent_id=task.parent_id,
            )
            blockers = [
                sibling.title
                for sibling in siblings
                if sibling.id != task.id
                and task.id in sibling.depends_on_task_ids
            ]
            if blockers:
                return {
                    'parent_task': parent.model_dump(mode='json'),
                    'final_response': (
                        f'任务“{task.title}”仍被以下子任务依赖，不能删除：'
                        + '、'.join(blockers)
                        + '。'
                    ),
                    'error_message': None,
                }

        payload = TaskDelete(
            user_id=task.user_id,
            expected_version=task.version,
        )
        confirmation_round = state.get('confirmation_round', 0) + 1
        request_id = state.get('request_id') or state['thread_id']
        identity = ':'.join(
            (
                task.user_id,
                state['thread_id'],
                request_id,
                'delete_task',
                str(confirmation_round),
            )
        )
        now = utc_now()
        pending = PendingAction(
            id=str(uuid5(NAMESPACE_URL, identity)),
            user_id=task.user_id,
            thread_id=state['thread_id'],
            action_type='delete_task',
            target_id=task.id,
            payload=payload.model_dump(mode='json'),
            idempotency_key=f'delete_task:{request_id}',
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
    except Exception as exc:
        return {'error_message': f'Could not prepare task deletion: {exc}'}

    warning = f'任务“{task.title}”将被永久删除且不可恢复。'
    if parent is not None:
        warning += f' 删除后会重新计算父任务“{parent.title}”的进度。'
    return {
        'pending_action': pending.model_dump(mode='json'),
        'parent_task': (
            parent.model_dump(mode='json') if parent is not None else None
        ),
        'confirmation_round': confirmation_round,
        'confirmation_status': 'pending',
        'review_action': None,
        'final_response': warning,
        'error_message': None,
    }


async def execute_task_delete(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    observability: ObservabilityService | None = None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    pending: PendingAction | None = None
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        if pending.target_id is None:
            raise ValueError('Task delete target_id is required')
        payload = TaskDelete.model_validate(pending.payload)
        confirmed = pending.confirmation_status == 'approved'
        result = await execute_observed_tool(
            observability,
            state=state,
            tool_name='delete_task',
            input_payload=pending.payload,
            confirmed=confirmed,
            idempotency_key=pending.idempotency_key,
            action_id=pending.id,
            operation=lambda: delete_task(
                repository=repository,
                user_id=payload.user_id,
                task_id=pending.target_id or '',
                delete_input=payload,
                idempotency_key=pending.idempotency_key,
                confirmed=confirmed,
            ),
        )
        selected = Task.model_validate(state.get('selected_task'))
    except Exception as exc:
        logger.warning(
            'tool=delete_task user_id=%s thread_id=%s task_id=%s '
            'confirmed=%s success=false error_type=%s',
            state.get('user_id'),
            state.get('thread_id'),
            pending.target_id if pending is not None else None,
            bool(pending and pending.confirmation_status == 'approved'),
            type(exc).__name__,
        )
        mapped = error_state(exc, trace_id=state.get('trace_id'))
        if mapped['error'] and _deletion_error_message(exc):
            mapped['final_response'] = _deletion_error_message(exc)
            mapped['error_message'] = _deletion_error_message(exc)
            mapped['error']['message'] = _deletion_error_message(exc)
        return mapped

    logger.info(
        'tool=delete_task user_id=%s thread_id=%s task_id=%s '
        'confirmed=true success=true replayed=%s',
        state.get('user_id'),
        state.get('thread_id'),
        result.deleted_task_id,
        result.replayed,
    )
    message = f'任务“{selected.title}”已永久删除。'
    if result.parent_task is not None:
        message += (
            f' 父任务“{result.parent_task.title}”当前进度为'
            f'{result.parent_task.progress}%，状态为'
            f'“{STATUS_LABELS[result.parent_task.status]}”。'
        )
    return {
        'deleted_task_id': result.deleted_task_id,
        'selected_task': None,
        'updated_task': None,
        'parent_task': (
            result.parent_task.model_dump(mode='json')
            if result.parent_task is not None
            else None
        ),
        'final_response': message,
        'error_message': None,
    }


async def execute_task_delete_batch(
    state: TaskAgentState,
    *,
    repository: TaskRepository | None,
    observability: ObservabilityService | None = None,
) -> dict[str, object]:
    if repository is None:
        return {'error_message': 'Task repository is not configured'}
    pending: PendingAction | None = None
    try:
        pending = PendingAction.model_validate(state.get('pending_action'))
        batch = TaskDeleteBatch.model_validate(pending.payload)
        confirmed = pending.confirmation_status == 'approved'
        result = await execute_observed_tool(
            observability,
            state=state,
            tool_name='delete_tasks_batch',
            input_payload={
                **pending.payload,
                'count': len(pending.payload.get('items', [])),
            },
            confirmed=confirmed,
            idempotency_key=pending.idempotency_key,
            action_id=pending.id,
            operation=lambda: delete_tasks_batch(
                repository=repository,
                batch_input=batch,
                idempotency_key=pending.idempotency_key,
                confirmed=confirmed,
            ),
        )
    except Exception as exc:
        logger.warning(
            'tool=delete_tasks_batch user_id=%s thread_id=%s task_count=%s '
            'confirmed=%s success=false error_type=%s',
            state.get('user_id'),
            state.get('thread_id'),
            len(state.get('deletion_tasks') or []),
            bool(pending and pending.confirmation_status == 'approved'),
            type(exc).__name__,
        )
        message = _deletion_error_message(exc)
        mapped = error_state(exc, trace_id=state.get('trace_id'))
        mapped['final_response'] = message
        mapped['error_message'] = message
        mapped['error']['message'] = message
        return mapped
    logger.info(
        'tool=delete_tasks_batch user_id=%s thread_id=%s task_count=%s '
        'confirmed=true success=true replayed=%s',
        state.get('user_id'),
        state.get('thread_id'),
        len(result.deleted_task_ids),
        result.replayed,
    )
    return {
        'deleted_task_ids': result.deleted_task_ids,
        'deleted_task_id': (
            result.deleted_task_ids[0]
            if len(result.deleted_task_ids) == 1
            else None
        ),
        'deletion_tasks': [],
        'selected_task': None,
        'parent_tasks': [
            parent.model_dump(mode='json') for parent in result.parent_tasks
        ],
        'parent_task': (
            result.parent_tasks[0].model_dump(mode='json')
            if len(result.parent_tasks) == 1
            else None
        ),
        'final_response': f'已永久删除 {len(result.deleted_task_ids)} 个任务。',
        'error_message': None,
    }


def _deletion_error_message(exc: Exception) -> str:
    if isinstance(exc, TaskNotFoundError):
        return '任务不存在或你无权访问，未执行删除。'
    if isinstance(exc, TaskVersionConflictError):
        return '任务已发生变化，请重新发起删除并确认最新内容。'
    if isinstance(exc, TaskDeletionBlockedError):
        message = str(exc)
        if message.startswith('Task is required by:'):
            blockers = message.partition(':')[2].strip()
            return f'该任务仍被以下任务依赖，不能删除：{blockers}。'
        return '该任务仍有直接子任务，不能删除。请先处理这些子任务。'
    if isinstance(exc, TaskRepositoryConcurrencyError):
        return '任务正在被并发修改，删除未执行，请稍后重试。'
    if isinstance(exc, TaskRepositoryConsistencyError):
        if 'idempotency key was reused' in str(exc):
            return '删除请求的幂等键已被其他操作使用，未执行删除。'
        return '任务数据关系不一致，删除未执行。'
    return '删除任务失败，未写入任何变更。'


async def _load_all_user_tasks(
    repository: TaskRepository,
    user_id: str,
) -> list[Task]:
    tasks: list[Task] = []
    offset = 0
    while True:
        page = await repository.list_tasks(
            TaskQuery(user_id=user_id, offset=offset, limit=100)
        )
        tasks.extend(page.items)
        offset += len(page.items)
        if offset >= page.total or not page.items:
            return tasks


async def _load_query_tasks(
    repository: TaskRepository,
    query: TaskQuery,
) -> list[Task]:
    tasks: list[Task] = []
    offset = 0
    while True:
        page = await repository.list_tasks(
            query.model_copy(update={'offset': offset, 'limit': 100})
        )
        tasks.extend(page.items)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            return tasks


def _normalize_text(value: str) -> str:
    return ''.join(character.casefold() for character in value if character.isalnum())


def _explicit_reference_matches(result: TaskMatchResult) -> list[Task]:
    allowed = {
        MatchKind.EXACT_ID,
        MatchKind.EXACT_TITLE,
        MatchKind.NORMALIZED_TITLE,
    }
    return [
        candidate.task
        for candidate in result.candidates
        if candidate.match_kind in allowed
    ]


def _task_search_text(task: Task) -> str:
    return _normalize_text(
        ' '.join(
            value
            for value in (task.title, task.description, task.category or '')
            if value
        )
    )


def _format_delete_preview(
    tasks: list[Task],
    *,
    timezone: str,
    blockers: list[str] | None = None,
) -> str:
    from zoneinfo import ZoneInfo

    lines = [f'删除计划共匹配 {len(tasks)} 个任务：', '']
    zone = ZoneInfo(timezone)
    for index, task in enumerate(tasks, start=1):
        deadline = (
            task.deadline.astimezone(zone).strftime('%Y-%m-%d %H:%M')
            if task.deadline is not None
            else '无截止时间'
        )
        lines.append(
            f'{index}. {task.title}｜{STATUS_LABELS[task.status]}｜{deadline}'
        )
    if blockers:
        lines.extend(['', '当前计划不能执行：'])
        lines.extend(f'- {message}' for message in dict.fromkeys(blockers))
    else:
        lines.extend(['', '以上任务将被永久删除且不可恢复，请确认。'])
    return '\n'.join(lines)
