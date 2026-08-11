import logging
from urllib.parse import quote

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from app.repositories.conversation import ConversationRepository
from app.schemas.agent import (
    AgentChatRequest,
    AgentConfirmRequest,
    AgentResponse,
)
from app.schemas.audit import PendingAction
from app.schemas.conversation import (
    DEFAULT_TENANT_ID,
    ConversationHistoryResponse,
    ConversationScope,
)
from app.schemas.draft import TaskDraft
from app.schemas.task import Task
from app.schemas.subtask import SubtaskPlan


logger = logging.getLogger(__name__)

_CONFIRMATION_HISTORY_LABELS = {
    'approve': '确认执行',
    'edit': '提交编辑',
    'reject': '取消操作',
    'regenerate': '重新生成',
}


class AgentThreadError(RuntimeError):
    pass


class AgentThreadNotFoundError(AgentThreadError):
    pass


class AgentThreadConflictError(AgentThreadError):
    pass


class TaskAgentService:
    def __init__(
        self,
        graph: CompiledStateGraph,
        *,
        conversation_repository: ConversationRepository | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> None:
        self._graph = graph
        self._conversation_repository = conversation_repository
        self._tenant_id = tenant_id

    async def chat(self, request: AgentChatRequest) -> AgentResponse:
        config = self._config(request.user_id, request.thread_id)
        snapshot = await self._graph.aget_state(config)
        if snapshot.next:
            raise AgentThreadConflictError(
                'This thread is waiting for confirmation'
            )

        previous = snapshot.values or {}
        initial_state = {
            'user_id': request.user_id,
            'thread_id': request.thread_id,
            'user_message': request.message,
            'timezone': request.timezone,
            'request_id': request.request_id,
            'intent_result': None,
            'pending_route': None,
            'pending_query_clarification': previous.get(
                'pending_query_clarification'
            ),
            'pending_task_selection': previous.get(
                'pending_task_selection'
            ),
            'pending_task_delete_selection': previous.get(
                'pending_task_delete_selection'
            ),
            'pending_task_draft_clarification': previous.get(
                'pending_task_draft_clarification'
            ),
            'pending_task_update_clarification': previous.get(
                'pending_task_update_clarification'
            ),
            'active_task_context': previous.get('active_task_context'),
            'task_collection_inputs': [],
            'task_draft_clarification_round': 0,
            'task_update_inputs': [],
            'task_update_clarification_round': 0,
            'intent': None,
            'intent_confidence': 0,
            'task_draft': None,
            'parsed_task': None,
            'pending_action': None,
            'confirmation_round': 0,
            'confirmation_status': None,
            'review_action': None,
            'last_handled_action_id': None,
            'regeneration_feedback': None,
            'user_priority': None,
            'created_task': None,
            'query_kind': None,
            'task_query_plan': None,
            'task_reference': None,
            'target_status': None,
            'task_results': [],
            'candidate_tasks': [],
            'selected_task': None,
            'parent_task': None,
            'existing_subtasks': [],
            'subtask_plan_draft': None,
            'subtask_plan': None,
            'created_subtasks': [],
            'decomposition_message': None,
            'updated_task': None,
            'deleted_task_id': None,
            'deleted_task_ids': [],
            'deletion_tasks': [],
            'parent_tasks': [],
            'task_delete_parse_result': None,
            'task_delete_route': None,
            'task_delete_selection_route': None,
            'resolved_delete_parent_id': None,
            'resolved_delete_references': {},
            'restored_from_cancelled': False,
            'task_update_result': None,
            'task_update': None,
            'task_update_message': None,
            'final_response': None,
            'error_message': None,
        }
        await self._graph.ainvoke(initial_state, config=config)
        response = await self._current_response(config, request.thread_id)
        await self._record_exchange(
            user_id=request.user_id,
            thread_id=request.thread_id,
            operation_id=f'chat:{request.request_id}',
            user_content=request.message,
            response=response,
        )
        return response

    async def confirm(self, request: AgentConfirmRequest) -> AgentResponse:
        config = self._config(request.user_id, request.thread_id)
        snapshot = await self._graph.aget_state(config)
        values = snapshot.values
        if not values:
            raise AgentThreadNotFoundError('Agent thread was not found')
        if (
            values.get('user_id') != request.user_id
            or values.get('thread_id') != request.thread_id
        ):
            raise AgentThreadNotFoundError('Agent thread was not found')

        if values.get('last_handled_action_id') == request.action_id:
            response = self._response_from_snapshot(
                snapshot,
                request.thread_id,
            )
            await self._record_confirmation(request, response)
            return response
        if not snapshot.next:
            raise AgentThreadConflictError('This thread is not awaiting confirmation')

        pending = PendingAction.model_validate(values.get('pending_action'))
        if pending.id != request.action_id:
            raise AgentThreadConflictError('action_id is not the current pending action')

        decision = request.model_dump(
            mode='json',
            include={'action_id', 'action', 'edits', 'feedback'},
            exclude_none=True,
        )
        await self._graph.ainvoke(Command(resume=decision), config=config)
        response = await self._current_response(config, request.thread_id)
        await self._record_confirmation(request, response)
        return response

    async def get_conversation_history(
        self,
        *,
        user_id: str,
        thread_id: str,
    ) -> ConversationHistoryResponse:
        scope = self._conversation_scope(user_id, thread_id)
        if self._conversation_repository is None:
            return ConversationHistoryResponse(**scope.model_dump())
        return await self._conversation_repository.get_history(scope=scope)

    async def _record_confirmation(
        self,
        request: AgentConfirmRequest,
        response: AgentResponse,
    ) -> None:
        action = request.action.value
        await self._record_exchange(
            user_id=request.user_id,
            thread_id=request.thread_id,
            operation_id=f'confirm:{request.action_id}:{action}',
            user_content=_CONFIRMATION_HISTORY_LABELS[action],
            response=response,
        )

    async def _record_exchange(
        self,
        *,
        user_id: str,
        thread_id: str,
        operation_id: str,
        user_content: str,
        response: AgentResponse,
    ) -> None:
        if self._conversation_repository is None:
            return
        try:
            await self._conversation_repository.append_exchange(
                scope=self._conversation_scope(user_id, thread_id),
                operation_id=operation_id,
                user_content=user_content,
                assistant_response=response,
            )
        except Exception:
            logger.exception(
                'conversation_history_write_failed tenant_id=%s user_id=%s '
                'conversation_id=%s operation_id=%s',
                self._tenant_id,
                user_id,
                thread_id,
                operation_id,
            )

    def _conversation_scope(
        self,
        user_id: str,
        thread_id: str,
    ) -> ConversationScope:
        return ConversationScope(
            tenant_id=self._tenant_id,
            user_id=user_id,
            conversation_id=thread_id,
        )

    async def _current_response(
        self,
        config: dict[str, dict[str, str]],
        thread_id: str,
    ) -> AgentResponse:
        snapshot = await self._graph.aget_state(config)
        return self._response_from_snapshot(snapshot, thread_id)

    @staticmethod
    def _response_from_snapshot(
        snapshot: StateSnapshot,
        thread_id: str,
    ) -> AgentResponse:
        values = snapshot.values
        pending = bool(snapshot.next)
        error = values.get('error_message')
        created = values.get('created_task')
        updated = values.get('updated_task')
        selected = values.get('selected_task')
        task_results = values.get('task_results') or []
        candidate_tasks = values.get('candidate_tasks') or []
        final = values.get('final_response')
        intent_result = values.get('intent_result') or {}
        task_update_result = values.get('task_update_result') or {}
        subtask_plan_data = values.get('subtask_plan')
        created_subtasks = values.get('created_subtasks') or []
        parent_data = values.get('parent_task')

        if pending:
            status = 'awaiting_confirmation'
            pending_action = values.get('pending_action') or {}
            action_type = pending_action.get('action_type')
            if action_type == 'update_task_status':
                message = '请确认任务状态更新'
            elif action_type == 'update_task':
                message = str(final or '请确认任务属性修改')
            elif action_type == 'create_subtasks_batch':
                message = str(final or '请确认任务拆解方案和批量创建')
            elif action_type in {'delete_task', 'delete_tasks_batch'}:
                message = str(final or '请确认永久删除任务')
            elif action_type == 'restore_task':
                message = str(final or '该任务已被取消，请确认是否先恢复为待办')
            else:
                message = '请确认任务创建草稿'
        elif intent_result.get('needs_clarification') is True:
            status = 'needs_clarification'
            message = str(final or intent_result.get('clarification_question'))
        elif task_update_result.get('needs_clarification') is True:
            status = 'needs_clarification'
            message = str(
                final or task_update_result.get('clarification_question')
            )
        elif values.get('pending_task_draft_clarification'):
            status = 'needs_clarification'
            message = str(final or '请补充创建任务所需的信息。')
        elif values.get('pending_task_update_clarification'):
            status = 'needs_clarification'
            message = str(final or '请补充任务修改所需的信息。')
        elif error:
            status = 'error'
            message = str(final or error)
        elif (
            created
            or created_subtasks
            or values.get('deleted_task_id')
            or values.get('deleted_task_ids')
        ):
            status = 'completed'
            message = str(final or '任务已创建。')
        elif values.get('confirmation_status') == 'rejected':
            status = 'rejected'
            message = str(final or '已取消任务操作。')
        elif candidate_tasks:
            status = 'needs_disambiguation'
            message = str(final or '找到多个候选任务，请选择。')
        else:
            status = 'completed'
            message = str(final or '请求已完成。')

        return AgentResponse(
            status=status,
            thread_id=thread_id,
            message=message,
            pending_action=(
                PendingAction.model_validate(values['pending_action'])
                if pending and values.get('pending_action')
                else None
            ),
            task_draft=(
                TaskDraft.model_validate(values['task_draft'])
                if pending and values.get('task_draft')
                else None
            ),
            task=(
                Task.model_validate(created or updated or selected)
                if created or updated or selected
                else None
            ),
            tasks=[Task.model_validate(task) for task in task_results],
            candidates=[
                Task.model_validate(task) for task in candidate_tasks
            ],
            subtask_plan=(
                SubtaskPlan.model_validate(subtask_plan_data)
                if subtask_plan_data
                else None
            ),
            subtasks=[
                Task.model_validate(task) for task in created_subtasks
            ],
            parent_task=(
                Task.model_validate(parent_data)
                if parent_data
                else None
            ),
            deleted_task_id=values.get('deleted_task_id'),
            deleted_task_ids=list(values.get('deleted_task_ids') or []),
            deletion_tasks=[
                Task.model_validate(task)
                for task in values.get('deletion_tasks') or []
            ],
            parent_tasks=[
                Task.model_validate(task)
                for task in values.get('parent_tasks') or []
            ],
        )

    @staticmethod
    def _config(user_id: str, thread_id: str) -> dict[str, dict[str, str]]:
        checkpoint_thread_id = ':'.join(
            (quote(user_id, safe=''), quote(thread_id, safe=''))
        )
        return {'configurable': {'thread_id': checkpoint_thread_id}}
