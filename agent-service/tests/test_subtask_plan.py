from datetime import datetime, timezone

import pytest

from app.schemas.subtask import SubtaskPlanDraft
from app.schemas.task import Task, TaskStatus
from app.services.subtask_plan import (
    SubtaskPlanValidationError,
    validate_subtask_plan,
)


def _parent() -> Task:
    return Task(
        id='parent-1',
        user_id='user-1',
        title='完成论文实验',
        estimated_minutes=180,
        deadline=datetime(2026, 8, 20, tzinfo=timezone.utc),
    )


def _draft() -> SubtaskPlanDraft:
    return SubtaskPlanDraft.model_validate(
        {
            'summary': '按实验流程拆解',
            'items': [
                {
                    'step_key': 'prepare',
                    'title': '整理实验配置',
                    'order': 1,
                    'estimated_minutes': 60,
                },
                {
                    'step_key': 'run',
                    'title': '运行实验',
                    'order': 2,
                    'depends_on': ['prepare'],
                    'estimated_minutes': 60,
                },
                {
                    'step_key': 'report',
                    'title': '汇总实验结果',
                    'order': 3,
                    'depends_on': ['run'],
                    'estimated_minutes': 60,
                },
            ],
        }
    )


def test_validate_subtask_plan_returns_parent_snapshot() -> None:
    parent = _parent()
    plan = validate_subtask_plan(
        parent=parent,
        draft=_draft(),
        existing_children=[],
    )

    assert plan.parent_task_id == parent.id
    assert plan.parent_version == parent.version
    assert [item.order for item in plan.items] == [1, 2, 3]
    assert plan.warnings == []


@pytest.mark.parametrize(
    'mutate,error',
    [
        (
            lambda data: data['items'][1].update({'order': 1}),
            '执行顺序必须唯一',
        ),
        (
            lambda data: data['items'][1].update(
                {'depends_on': ['missing']}
            ),
            '不存在的依赖',
        ),
        (
            lambda data: data['items'][0].update(
                {'deadline': '2026-08-21T00:00:00+00:00'}
            ),
            '截止时间晚于父任务',
        ),
    ],
)
def test_validate_subtask_plan_rejects_invalid_structure(
    mutate: object,
    error: str,
) -> None:
    payload = _draft().model_dump(mode='json')
    mutate(payload)  # type: ignore[operator]
    with pytest.raises(SubtaskPlanValidationError, match=error):
        validate_subtask_plan(
            parent=_parent(),
            draft=SubtaskPlanDraft.model_validate(payload),
            existing_children=[],
        )


def test_validate_subtask_plan_rejects_existing_active_duplicate() -> None:
    existing = Task(
        id='child-1',
        user_id='user-1',
        parent_id='parent-1',
        title='运行实验',
        status=TaskStatus.DOING,
    )
    with pytest.raises(SubtaskPlanValidationError, match='已有有效子任务重复'):
        validate_subtask_plan(
            parent=_parent(),
            draft=_draft(),
            existing_children=[existing],
        )


def test_validate_subtask_plan_rejects_nested_decomposition() -> None:
    parent = _parent().model_copy(update={'parent_id': 'root-task'})
    with pytest.raises(SubtaskPlanValidationError, match='不支持继续拆解子任务'):
        validate_subtask_plan(
            parent=parent,
            draft=_draft(),
            existing_children=[],
        )
