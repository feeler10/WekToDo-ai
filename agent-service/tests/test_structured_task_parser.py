from collections.abc import Iterable
from datetime import datetime, timezone

import pytest

from app.graph.parser import StructuredOutputTaskParser, TaskParsingError
from app.schemas.draft import TaskDraftCandidate


class FakeRunnable:
    def __init__(self, outputs: Iterable[object]) -> None:
        self._outputs = iter(outputs)
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        output = next(self._outputs)
        if isinstance(output, Exception):
            raise output
        return output


class FakeStructuredModel:
    def __init__(self, runnable: FakeRunnable) -> None:
        self.runnable = runnable
        self.schema: type[TaskDraftCandidate] | None = None
        self.method: str | None = None

    def with_structured_output(
        self,
        schema: type[TaskDraftCandidate],
        **kwargs: object,
    ) -> FakeRunnable:
        self.schema = schema
        self.method = str(kwargs.get('method'))
        return self.runnable


@pytest.mark.anyio
async def test_parser_uses_structured_output_and_retries_validation_failure() -> None:
    runnable = FakeRunnable(
        [
            {'title': '提交论文', 'semantic_importance': 101},
            {'title': '提交论文', 'deadline': '2026-08-07T23:59:00+08:00'},
        ]
    )
    model = FakeStructuredModel(runnable)
    parser = StructuredOutputTaskParser(
        lambda: model,
        max_attempts=2,
        clock=lambda: datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    result = await parser.parse('下周五前提交论文', timezone='Asia/Shanghai')

    assert result['title'] == '提交论文'
    assert result['deadline'] == '2026-08-07T23:59:00+08:00'
    assert model.schema is TaskDraftCandidate
    assert model.method == 'json_mode'
    assert len(runnable.inputs) == 2
    assert 'Return JSON only' in runnable.inputs[0][0][1]
    assert 'title' in runnable.inputs[0][0][1]
    assert 'failed Pydantic validation' in runnable.inputs[1][0][1]


@pytest.mark.anyio
async def test_parser_stops_after_configured_attempt_limit() -> None:
    runnable = FakeRunnable(
        [
            {'semantic_importance': 101},
            {'semantic_importance': 101},
        ]
    )
    parser = StructuredOutputTaskParser(lambda: FakeStructuredModel(runnable), max_attempts=2)

    with pytest.raises(TaskParsingError, match='after 2 attempts'):
        await parser.parse('创建任务', timezone='UTC')

    assert len(runnable.inputs) == 2


@pytest.mark.anyio
async def test_parser_accepts_partial_candidate_without_title() -> None:
    runnable = FakeRunnable(
        [
            {
                'description': '先记下来，名称稍后补充',
                'missing_fields': ['title'],
                'clarification_question': '这个任务叫什么？',
            }
        ]
    )
    model = FakeStructuredModel(runnable)
    parser = StructuredOutputTaskParser(lambda: model)

    result = await parser.parse('帮我建一个任务', timezone='UTC')

    assert result['title'] is None
    assert result['missing_fields'] == ['title']
    assert result['clarification_question'] == '这个任务叫什么？'
    assert model.schema is TaskDraftCandidate


@pytest.mark.anyio
@pytest.mark.parametrize('method', ['json_schema', 'function_calling'])
async def test_parser_forwards_explicit_structured_output_method(
    method: str,
) -> None:
    runnable = FakeRunnable([{'title': '提交论文'}])
    model = FakeStructuredModel(runnable)
    parser = StructuredOutputTaskParser(lambda: model, method=method)

    result = await parser.parse('创建任务', timezone='UTC')

    assert result['title'] == '提交论文'
    assert model.method == method
    assert 'Return JSON only' not in runnable.inputs[0][0][1]
