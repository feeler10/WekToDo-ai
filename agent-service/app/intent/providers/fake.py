from collections.abc import Mapping
from datetime import datetime

from app.intent.enums import (
    ClarificationReason,
    IntentType,
    TimeScope,
)
from app.intent.exceptions import InvalidIntentOutputError
from app.intent.models import (
    IntentRecognitionContext,
    IntentResult,
    TaskQueryIntent,
)
from app.schemas.task import TaskPriority, TaskStatus


class FakeIntentClassifier:
    def __init__(
        self,
        result: IntentResult | Mapping[str, object] | None = None,
        *,
        responses: Mapping[
            str,
            IntentResult | Mapping[str, object],
        ] | None = None,
        error: Exception | None = None,
        intent: IntentType | str | None = None,
        confidence: float = 1.0,
        reason: str = '测试结果',
        task_reference: str | None = None,
        target_status: TaskStatus | str | None = None,
        query: TaskQueryIntent | Mapping[str, object] | None = None,
        time_scope: TimeScope | str | None = None,
        statuses: set[TaskStatus | str] | None = None,
        priorities: set[TaskPriority | str] | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        raw_time_expression: str | None = None,
        needs_clarification: bool = False,
        clarification_reason: ClarificationReason | str | None = None,
        clarification_question: str | None = None,
    ) -> None:
        shortcut_used = any(
            value is not None
            for value in (
                intent,
                task_reference,
                target_status,
                query,
                time_scope,
                statuses,
                priorities,
                start_at,
                end_at,
                raw_time_expression,
                clarification_reason,
                clarification_question,
            )
        ) or needs_clarification
        if result is not None and shortcut_used:
            raise ValueError(
                'result cannot be combined with fake result shortcut fields'
            )
        if query is not None and any(
            value is not None
            for value in (
                time_scope,
                statuses,
                priorities,
                start_at,
                end_at,
                raw_time_expression,
            )
        ):
            raise ValueError(
                'query cannot be combined with query shortcut fields'
            )

        if shortcut_used:
            resolved_intent = intent
            if resolved_intent is None and any(
                value is not None
                for value in (
                    query,
                    time_scope,
                    statuses,
                    priorities,
                    start_at,
                    end_at,
                    raw_time_expression,
                )
            ):
                resolved_intent = IntentType.QUERY_TASKS
            if resolved_intent is None:
                raise ValueError('intent is required for a fake result shortcut')

            resolved_query = query
            if resolved_query is None and any(
                value is not None
                for value in (
                    time_scope,
                    statuses,
                    priorities,
                    start_at,
                    end_at,
                    raw_time_expression,
                )
            ):
                resolved_query = TaskQueryIntent(
                    time_scope=time_scope or TimeScope.UNSPECIFIED,
                    statuses=statuses,
                    priorities=priorities,
                    start_at=start_at,
                    end_at=end_at,
                    raw_time_expression=raw_time_expression,
                )
            result = IntentResult.model_validate(
                {
                    'intent': resolved_intent,
                    'confidence': confidence,
                    'reason': reason,
                    'task_reference': task_reference,
                    'target_status': target_status,
                    'query': resolved_query,
                    'needs_clarification': needs_clarification,
                    'clarification_reason': clarification_reason,
                    'clarification_question': clarification_question,
                }
            )

        self._result = result
        self._responses = dict(responses or {})
        self._error = error
        self.calls: list[IntentRecognitionContext] = []

    async def classify(
        self,
        context: IntentRecognitionContext,
    ) -> IntentResult:
        self.calls.append(context)
        if self._error is not None:
            raise self._error
        candidate = self._responses.get(context.message, self._result)
        if candidate is None:
            raise InvalidIntentOutputError(
                f'No fake intent result configured for message: {context.message}'
            )
        return IntentResult.model_validate(candidate)
