import json
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.draft import TaskDraftCandidate, TaskDraftFieldName
from app.schemas.task import Task
from app.schemas.task_attribute_update import TaskUpdateParseResult
from app.services.task_draft_clarification import missing_task_draft_fields


class MultiTurnExpectation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    route: Literal['clarify', 'ready']
    missing_fields: list[TaskDraftFieldName] | None = None
    title: str | None = None
    changes: dict[str, Any] | None = None


class MultiTurnEvaluationCase(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str = Field(min_length=1)
    kind: Literal['create_task', 'update_task']
    timezone: str = Field(default='Asia/Shanghai', min_length=1)
    current_datetime: AwareDatetime
    messages: list[str] = Field(min_length=2, max_length=8)
    expected: list[MultiTurnExpectation] = Field(min_length=2, max_length=8)
    current_task: Task | None = None

    @model_validator(mode='after')
    def validate_case(self) -> 'MultiTurnEvaluationCase':
        if len(self.messages) != len(self.expected):
            raise ValueError('messages and expected must have the same length')
        if self.kind == 'update_task' and self.current_task is None:
            raise ValueError('current_task is required for update_task cases')
        if self.kind == 'create_task' and self.current_task is not None:
            raise ValueError('current_task is only allowed for update_task cases')
        return self


class MultiTurnEvaluationDataset(BaseModel):
    model_config = ConfigDict(extra='forbid')

    version: str = Field(pattern=r'^\d+\.\d+\.\d+$')
    cases: list[MultiTurnEvaluationCase] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_case_ids(self) -> 'MultiTurnEvaluationDataset':
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError('evaluation case ids must be unique')
        return self


def load_multiturn_dataset(path: Path) -> MultiTurnEvaluationDataset:
    return MultiTurnEvaluationDataset.model_validate_json(
        path.read_text(encoding='utf-8')
    )


def evaluate_create_output(
    output: object,
    expected: MultiTurnExpectation,
) -> list[str]:
    candidate = TaskDraftCandidate.model_validate(output)
    missing = [field.value for field in missing_task_draft_fields(candidate)]
    actual_route = 'clarify' if missing else 'ready'
    failures = _compare_route(actual_route, expected.route)
    if expected.missing_fields is not None:
        expected_missing = [field.value for field in expected.missing_fields]
        if missing != expected_missing:
            failures.append(
                f'missing_fields expected={expected_missing} actual={missing}'
            )
    if expected.title is not None and candidate.title != expected.title:
        failures.append(
            f'title expected={expected.title!r} actual={candidate.title!r}'
        )
    return failures


def evaluate_update_output(
    output: object,
    expected: MultiTurnExpectation,
) -> list[str]:
    result = TaskUpdateParseResult.model_validate(output)
    actual_route = 'clarify' if result.needs_clarification else 'ready'
    failures = _compare_route(actual_route, expected.route)
    if expected.changes is not None:
        actual_changes = {
            change.field.value: (
                None if change.operation.value == 'CLEAR' else change.value
            )
            for change in result.changes
        }
        expected_fields = set(expected.changes)
        actual_fields = set(actual_changes)
        if actual_fields != expected_fields:
            failures.append(
                f'change_fields expected={sorted(expected_fields)} '
                f'actual={sorted(actual_fields)}'
            )
        for field, value in expected.changes.items():
            if actual_changes.get(field) != value:
                failures.append(
                    f'change[{field}] expected={value!r} '
                    f'actual={actual_changes.get(field)!r}'
                )
    return failures


def dump_evaluation_value(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _compare_route(actual: str, expected: str) -> list[str]:
    if actual == expected:
        return []
    return [f'route expected={expected!r} actual={actual!r}']
