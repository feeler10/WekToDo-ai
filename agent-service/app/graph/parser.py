import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from app.schemas.draft import TaskDraftCandidate
from app.schemas.task import utc_now


ParsedTaskDraft = TaskDraftCandidate
StructuredOutputMethod = Literal[
    'json_schema',
    'function_calling',
    'json_mode',
]

_SUPPORTED_METHODS = frozenset(
    {'json_schema', 'function_calling', 'json_mode'}
)


class TaskParser(Protocol):
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]: ...


class StructuredOutputRunnable(Protocol):
    async def ainvoke(self, input: object) -> object: ...


class StructuredOutputModel(Protocol):
    def with_structured_output(
        self,
        schema: type[BaseModel],
        **kwargs: Any,
    ) -> StructuredOutputRunnable: ...


class TaskParsingError(RuntimeError):
    pass


class StructuredOutputTaskParser:
    def __init__(
        self,
        model_factory: Callable[[], StructuredOutputModel],
        *,
        method: StructuredOutputMethod = 'json_mode',
        max_attempts: int = 3,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if max_attempts < 1:
            raise ValueError('max_attempts must be at least 1')
        if method not in _SUPPORTED_METHODS:
            raise ValueError(f'unsupported structured output method: {method}')
        self._model_factory = model_factory
        self._method = method
        self._max_attempts = max_attempts
        self._clock = clock

    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        runnable = self._model_factory().with_structured_output(
            TaskDraftCandidate,
            method=self._method,
        )
        validation_feedback = ''
        last_error: Exception | None = None

        for attempt in range(1, self._max_attempts + 1):
            prompt = self._prompt(
                user_message,
                timezone=timezone,
                validation_feedback=validation_feedback,
            )
            try:
                output = await runnable.ainvoke(prompt)
                draft = (
                    output
                    if isinstance(output, TaskDraftCandidate)
                    else TaskDraftCandidate.model_validate(output)
                )
                return draft.model_dump(mode='json')
            except (ValidationError, TypeError, ValueError) as exc:
                last_error = exc
                validation_feedback = (
                    f'Previous structured output failed Pydantic validation: {exc}. '
                    'Return a corrected object only.'
                )
                if attempt == self._max_attempts:
                    break

        raise TaskParsingError(
            f'Task parsing failed after {self._max_attempts} attempts: {last_error}'
        )

    def _prompt(
        self,
        user_message: str,
        *,
        timezone: str,
        validation_feedback: str,
    ) -> list[tuple[str, str]]:
        now = self._clock()
        format_instruction = ''
        if self._method == 'json_mode':
            schema = json.dumps(
                TaskDraftCandidate.model_json_schema(),
                ensure_ascii=False,
                separators=(',', ':'),
            )
            format_instruction = (
                'Return JSON only, without Markdown or explanations. '
                f'The JSON must conform to this schema: {schema}. '
            )
        system = (
            'Extract exactly one task draft. Do not decompose it into subtasks. '
            f'{format_instruction}'
            'All datetimes must include a UTC offset. '
            f'The user timezone is {timezone}; current UTC time is {now.isoformat()}. '
            'Scores must be integers from 0 to 100. '
            'Do not invent a title or other facts the user did not provide. '
            'missing_fields is not a list of all optional information that the '
            'user omitted. Never include description, category, deadline, or '
            'estimated_minutes merely because it was not provided; keep its '
            'normal empty or null value instead. Only include title when no '
            'identifiable title exists, or include a field the user explicitly '
            'mentioned but whose value is too ambiguous to parse reliably. '
            'If no identifiable task title is available, return title=null and '
            'include "title" in missing_fields. If an explicitly mentioned '
            'field is ambiguous and blocks a reliable draft, include that field '
            'in missing_fields, set its value to null, and provide one concise '
            'clarification_question. Phrases such as "月底前后", "过几天", '
            'and "尽快" are ambiguous deadlines: never choose a date for them; '
            'include only "deadline" in missing_fields unless another '
            'explicitly mentioned field is independently ambiguous. '
            'When the user supplies corrections across multiple labeled rounds, '
            'later explicit values override earlier conflicting values. '
            f'{validation_feedback}'
        )
        return [('system', system), ('human', user_message)]
