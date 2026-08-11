from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.multiturn import (
    MultiTurnEvaluationDataset,
    MultiTurnExpectation,
    evaluate_create_output,
    evaluate_update_output,
    load_multiturn_dataset,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = (
    REPOSITORY_ROOT / 'evaluation' / 'datasets' / 'multiturn_cases.v1.json'
)


def test_versioned_multiturn_dataset_is_valid() -> None:
    dataset = load_multiturn_dataset(DATASET_PATH)

    assert dataset.version == '1.0.0'
    assert {case.kind for case in dataset.cases} == {
        'create_task',
        'update_task',
    }
    assert len({case.id for case in dataset.cases}) == len(dataset.cases)


def test_create_evaluation_checks_route_missing_fields_and_title() -> None:
    expected = MultiTurnExpectation(
        route='clarify',
        missing_fields=['deadline'],
        title='项目周报',
    )

    failures = evaluate_create_output(
        {
            'title': '初版周报',
            'missing_fields': ['deadline'],
            'clarification_question': '具体截止到什么时候？',
        },
        expected,
    )

    assert failures == [
        "title expected='项目周报' actual='初版周报'"
    ]


def test_update_evaluation_checks_minimal_expected_changes() -> None:
    expected = MultiTurnExpectation(
        route='ready',
        changes={'title': '每天早上接水'},
    )

    failures = evaluate_update_output(
        {
            'changes': [
                {
                    'field': 'title',
                    'operation': 'SET',
                    'value': '每天早上接水',
                }
            ],
            'reason': '修改标题',
        },
        expected,
    )

    assert failures == []


def test_update_evaluation_rejects_unrequested_extra_changes() -> None:
    expected = MultiTurnExpectation(
        route='ready',
        changes={'title': '每天早上接水'},
    )

    failures = evaluate_update_output(
        {
            'changes': [
                {
                    'field': 'title',
                    'operation': 'SET',
                    'value': '每天早上接水',
                },
                {
                    'field': 'category',
                    'operation': 'SET',
                    'value': '生活',
                },
            ],
            'reason': '修改标题和分类',
        },
        expected,
    )

    assert failures == [
        "change_fields expected=['title'] actual=['category', 'title']"
    ]


def test_multiturn_dataset_rejects_mismatched_turn_counts() -> None:
    with pytest.raises(ValidationError, match='same length'):
        MultiTurnEvaluationDataset.model_validate(
            {
                'version': '1.0.0',
                'cases': [
                    {
                        'id': 'broken',
                        'kind': 'create_task',
                        'current_datetime': '2026-08-11T16:00:00+08:00',
                        'messages': ['创建任务', '标题叫测试'],
                        'expected': [
                            {'route': 'clarify'},
                            {'route': 'ready'},
                            {'route': 'ready'},
                        ],
                    }
                ],
            }
        )
