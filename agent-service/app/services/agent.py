from urllib.parse import quote

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from app.schemas.agent import (
    AgentChatRequest,
    AgentConfirmRequest,
    AgentResponse,
)
from app.schemas.audit import PendingAction
from app.schemas.draft import TaskDraft
from app.schemas.task import Task


class AgentThreadError(RuntimeError):
    pass


class AgentThreadNotFoundError(AgentThreadError):
    pass


class AgentThreadConflictError(AgentThreadError):
    pass


class TaskAgentService:
    def __init__(self, graph: CompiledStateGraph) -> None:
        self._graph = graph

    async def chat(self, request: AgentChatRequest) -> AgentResponse:
        config = self._config(request.user_id, request.thread_id)
        snapshot = await self._graph.aget_state(config)
        if snapshot.next:
            raise AgentThreadConflictError(
                'This thread is waiting for confirmation'
            )

        initial_state = {
            'user_id': request.user_id,
            'thread_id': request.thread_id,
            'user_message': request.message,
            'timezone': request.timezone,
            'request_id': request.request_id,
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
            'task_reference': None,
            'target_status': None,
            'task_results': [],
            'candidate_tasks': [],
            'selected_task': None,
            'updated_task': None,
            'final_response': None,
            'error_message': None,
        }
        await self._graph.ainvoke(initial_state, config=config)
        return await self._current_response(config, request.thread_id)

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
            return self._response_from_snapshot(snapshot, request.thread_id)
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
        return await self._current_response(config, request.thread_id)

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

        if pending:
            status = 'awaiting_confirmation'
            pending_action = values.get('pending_action') or {}
            message = (
                'Review the task status update'
                if pending_action.get('action_type') == 'update_task_status'
                else 'Review the task draft before creation'
            )
        elif error:
            status = 'error'
            message = str(final or error)
        elif created:
            status = 'completed'
            message = str(final or 'Task created')
        elif values.get('confirmation_status') == 'rejected':
            status = 'rejected'
            message = str(final or 'Task operation rejected')
        elif candidate_tasks:
            status = 'needs_disambiguation'
            message = str(final or 'Multiple tasks matched')
        else:
            status = 'completed'
            message = str(final or 'Request completed')

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
        )

    @staticmethod
    def _config(user_id: str, thread_id: str) -> dict[str, dict[str, str]]:
        checkpoint_thread_id = ':'.join(
            (quote(user_id, safe=''), quote(thread_id, safe=''))
        )
        return {'configurable': {'thread_id': checkpoint_thread_id}}
