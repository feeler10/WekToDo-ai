from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.graph.task_delete_parser import StructuredOutputTaskDeleteParser
from app.schemas.task_deletion import TaskDeleteParseResult


NOW = datetime(2026, 8, 11, 2, tzinfo=timezone.utc)


class FixedRunnable:
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.inputs: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        return self.output


class FixedModel:
    def __init__(self, runnable: FixedRunnable) -> None:
        self.runnable = runnable
        self.schemas: list[type[object]] = []

    def with_structured_output(
        self,
        schema: type[object],
        **_kwargs: object,
    ) -> FixedRunnable:
        self.schemas.append(schema)
        return self.runnable


@pytest.mark.anyio
async def test_delete_parser_returns_controlled_custom_range() -> None:
    runnable = FixedRunnable(
        {
            'query': {
                'time_scope': 'CUSTOM',
                'start_at': '2026-08-01T00:00:00+08:00',
                'end_at': '2026-08-11T00:00:00+08:00',
            },
            'delete_all_matches': True,
            'explicit_all_tasks': False,
            'reason': '用户指定了日期区间',
        }
    )
    model = FixedModel(runnable)
    parser = StructuredOutputTaskDeleteParser(lambda: model)

    result = await parser.parse(
        '删除八月一日到十日的全部任务',
        timezone='Asia/Shanghai',
        current_datetime=NOW,
    )

    parsed = TaskDeleteParseResult.model_validate(result)
    assert parsed.query.time_scope.value == 'CUSTOM'
    assert parsed.query.start_at is not None
    assert parsed.query.start_at.isoformat() == '2026-08-01T00:00:00+08:00'
    assert parsed.query.end_at is not None
    assert parsed.query.end_at.isoformat() == '2026-08-11T00:00:00+08:00'
    assert model.schemas == [TaskDeleteParseResult]
    assert 'Current datetime: 2026-08-11T02:00:00+00:00' in str(
        runnable.inputs[0]
    )


@pytest.mark.anyio
async def test_delete_parser_represents_cancelled_and_keyword_ranges() -> None:
    cancelled = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL', 'statuses': ['CANCELLED']},
            'delete_all_matches': True,
            'reason': '所有已取消任务',
        }
    )
    keyword = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'keywords': ['论文'],
            'match_mode': 'CONTAINS',
            'delete_all_matches': True,
            'reason': '所有包含论文的任务',
        }
    )

    assert {status.value for status in cancelled.query.statuses or set()} == {
        'CANCELLED'
    }
    assert keyword.keywords == ['论文']
    assert keyword.match_mode.value == 'CONTAINS'


def test_delete_parser_represents_parent_scoped_child_reference() -> None:
    parsed = TaskDeleteParseResult.model_validate(
        {
            'query': {'time_scope': 'ALL'},
            'target_scope': 'DIRECT_CHILDREN',
            'parent_reference': '完成扩散模型论文实验',
            'task_references': ['结果分析与实验报告撰写任务'],
            'reason': '指定父任务下的单个子任务',
        }
    )

    assert parsed.target_scope.value == 'DIRECT_CHILDREN'
    assert parsed.parent_reference == '完成扩散模型论文实验'
    assert parsed.task_references == ['结果分析与实验报告撰写任务']


def test_direct_children_scope_requires_parent_reference() -> None:
    with pytest.raises(ValidationError, match='parent_reference'):
        TaskDeleteParseResult.model_validate(
            {
                'target_scope': 'DIRECT_CHILDREN',
                'delete_all_matches': True,
                'reason': '缺少父任务',
            }
        )
