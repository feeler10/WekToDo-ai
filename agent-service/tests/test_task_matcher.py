import pytest

from app.matching.factory import (
    TaskMatcherProvider,
    UnsupportedTaskMatcherProviderError,
    create_task_matcher,
)
from app.matching.keyword import KeywordTaskMatcher
from app.matching.models import MatchKind
from app.schemas.task import Task


def _task(task_id: str, title: str, *, user_id: str = 'user-1') -> Task:
    return Task(id=task_id, user_id=user_id, title=title)


def test_factory_uses_keyword_provider_by_default() -> None:
    assert isinstance(create_task_matcher(), KeywordTaskMatcher)
    assert isinstance(
        create_task_matcher(TaskMatcherProvider.KEYWORD),
        KeywordTaskMatcher,
    )


@pytest.mark.parametrize('provider', ['vector', 'hybrid', 'unknown'])
def test_factory_fails_explicitly_for_unavailable_providers(
    provider: str,
) -> None:
    with pytest.raises(UnsupportedTaskMatcherProviderError):
        create_task_matcher(provider)


def test_empty_reference_never_matches_all_tasks() -> None:
    result = KeywordTaskMatcher().match(
        reference='   ',
        user_id='user-1',
        tasks=[_task('task-1', '论文实验')],
    )

    assert result.candidates == []
    assert result.unique_task is None


@pytest.mark.parametrize(
    ('reference', 'expected_kind'),
    [
        ('task-2', MatchKind.EXACT_ID),
        ('论文实验', MatchKind.EXACT_TITLE),
        (' 论 文 实 验 ', MatchKind.NORMALIZED_TITLE),
        ('论文', MatchKind.KEYWORD),
    ],
)
def test_match_precedence_returns_highest_matching_tier(
    reference: str,
    expected_kind: MatchKind,
) -> None:
    tasks = [
        _task('task-1', '论文实验'),
        _task('task-2', '代码复查'),
    ]

    result = KeywordTaskMatcher().match(
        reference=reference,
        user_id='user-1',
        tasks=tasks,
    )

    assert result.unique_task is not None
    expected_id = 'task-2' if reference == 'task-2' else 'task-1'
    assert result.unique_task.id == expected_id
    assert result.candidates[0].match_kind == expected_kind


def test_normalization_handles_small_task_suffix_without_synonyms() -> None:
    result = KeywordTaskMatcher().match(
        reference='论文实验任务',
        user_id='user-1',
        tasks=[_task('task-1', '论文实验')],
    )

    assert result.unique_task is not None
    assert result.candidates[0].match_kind == MatchKind.NORMALIZED_TITLE


def test_zero_unique_and_multiple_results_share_one_contract() -> None:
    matcher = KeywordTaskMatcher()
    tasks = [
        _task('task-b', '论文实验'),
        _task('task-a', '论文实验'),
        _task('task-c', '代码复查'),
    ]

    zero = matcher.match(
        reference='不存在', user_id='user-1', tasks=tasks
    )
    unique = matcher.match(
        reference='代码', user_id='user-1', tasks=tasks
    )
    multiple = matcher.match(
        reference='论文实验', user_id='user-1', tasks=tasks
    )

    assert zero.tasks == []
    assert unique.unique_task is not None
    assert unique.unique_task.id == 'task-c'
    assert [task.id for task in multiple.tasks] == ['task-a', 'task-b']
    assert multiple.unique_task is None


def test_matcher_filters_foreign_tasks_before_matching() -> None:
    result = KeywordTaskMatcher().match(
        reference='共享任务',
        user_id='user-1',
        tasks=[
            _task('foreign', '共享任务', user_id='user-2'),
            _task('owned', '共享任务', user_id='user-1'),
        ],
    )

    assert result.unique_task is not None
    assert result.unique_task.id == 'owned'
    assert all(task.user_id == 'user-1' for task in result.tasks)
