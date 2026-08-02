from enum import Enum

from app.matching.base import TaskMatcher
from app.matching.keyword import KeywordTaskMatcher


class TaskMatcherProvider(str, Enum):
    KEYWORD = 'keyword'
    VECTOR = 'vector'
    HYBRID = 'hybrid'


class UnsupportedTaskMatcherProviderError(ValueError):
    pass


def create_task_matcher(
    provider: TaskMatcherProvider | str = TaskMatcherProvider.KEYWORD,
) -> TaskMatcher:
    try:
        selected = TaskMatcherProvider(provider)
    except ValueError as exc:
        raise UnsupportedTaskMatcherProviderError(
            f'Unsupported task matcher provider: {provider}'
        ) from exc
    if selected == TaskMatcherProvider.KEYWORD:
        return KeywordTaskMatcher()
    raise UnsupportedTaskMatcherProviderError(
        f'Task matcher provider is not implemented: {selected.value}'
    )
