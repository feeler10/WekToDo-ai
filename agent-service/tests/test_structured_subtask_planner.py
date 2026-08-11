from collections.abc import Iterable
from datetime import datetime, timezone

import pytest

from app.graph.subtask_planner import (
    StructuredOutputSubtaskPlanner,
    SubtaskPlanningError,
)
from app.schemas.subtask import SubtaskPlanDraft
from app.schemas.task import Task


class FakeRunnable:
    def __init__(self, outputs: Iterable[object]) -> None:
        self._outputs = iter(outputs)
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        return next(self._outputs)


class FakeModel:
    def __init__(self, runnable: FakeRunnable) -> None:
        self.runnable = runnable
        self.schema: type[SubtaskPlanDraft] | None = None
        self.method: str | None = None

    def with_structured_output(
        self,
        schema: type[SubtaskPlanDraft],
        **kwargs: object,
    ) -> FakeRunnable:
        self.schema = schema
        self.method = str(kwargs.get('method'))
        return self.runnable


def _valid_plan() -> dict[str, object]:
    return {
        'summary': '测试方案',
        'items': [
            {'step_key': 'a', 'title': '步骤 A', 'order': 1},
            {'step_key': 'b', 'title': '步骤 B', 'order': 2},
            {'step_key': 'c', 'title': '步骤 C', 'order': 3},
        ],
    }


@pytest.mark.anyio
async def test_subtask_planner_retries_schema_failure() -> None:
    runnable = FakeRunnable([{'summary': '缺少步骤'}, _valid_plan()])
    model = FakeModel(runnable)
    planner = StructuredOutputSubtaskPlanner(
        lambda: model,
        max_attempts=2,
        clock=lambda: datetime(2026, 8, 10, tzinfo=timezone.utc),
    )

    result = await planner.generate(
        parent=Task(id='parent', user_id='user-1', title='父任务'),
        user_message='拆解父任务',
        existing_children=[],
        timezone='Asia/Shanghai',
    )

    assert len(result['items']) == 3
    assert model.schema is SubtaskPlanDraft
    assert model.method == 'json_mode'
    assert len(runnable.inputs) == 2
    assert 'Previous output failed schema validation' in runnable.inputs[1][0][1]


@pytest.mark.anyio
async def test_subtask_planner_stops_at_attempt_limit() -> None:
    runnable = FakeRunnable([{}, {}])
    planner = StructuredOutputSubtaskPlanner(
        lambda: FakeModel(runnable),
        max_attempts=2,
    )

    with pytest.raises(SubtaskPlanningError, match='after 2 attempts'):
        await planner.generate(
            parent=Task(id='parent', user_id='user-1', title='父任务'),
            user_message='拆解父任务',
            existing_children=[],
            timezone='UTC',
        )
