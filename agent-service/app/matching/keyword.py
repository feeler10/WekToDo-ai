import re
from collections.abc import Callable, Sequence

from app.matching.base import TaskMatcher
from app.matching.models import MatchKind, TaskMatchCandidate, TaskMatchResult
from app.schemas.task import Task


_IGNORED_PUNCTUATION = re.compile(r'[\s，,。！？!?：:；;、“”"\'‘’]+')
_REFERENCE_SUFFIXES = ('这个任务', '这项任务', '任务')


class KeywordTaskMatcher(TaskMatcher):
    def match(
        self,
        *,
        reference: str,
        user_id: str,
        tasks: Sequence[Task],
    ) -> TaskMatchResult:
        stripped_reference = reference.strip()
        if not stripped_reference:
            return TaskMatchResult(
                user_id=user_id,
                reference=reference,
                candidates=[],
            )

        owned_tasks = [task for task in tasks if task.user_id == user_id]
        tiers: tuple[
            tuple[MatchKind, Callable[[Task], bool]],
            ...,
        ] = (
            (
                MatchKind.EXACT_ID,
                lambda task: task.id == stripped_reference,
            ),
            (
                MatchKind.EXACT_TITLE,
                lambda task: task.title.strip() == stripped_reference,
            ),
            (
                MatchKind.NORMALIZED_TITLE,
                lambda task: _normalize(task.title)
                == _normalize(stripped_reference),
            ),
            (
                MatchKind.KEYWORD,
                lambda task: _is_keyword_match(
                    stripped_reference,
                    task.title,
                ),
            ),
        )
        for match_kind, predicate in tiers:
            matched = [task for task in owned_tasks if predicate(task)]
            if matched:
                matched.sort(key=_stable_task_key)
                return TaskMatchResult(
                    user_id=user_id,
                    reference=reference,
                    candidates=[
                        TaskMatchCandidate(
                            task=task,
                            match_kind=match_kind,
                        )
                        for task in matched
                    ],
                )

        return TaskMatchResult(
            user_id=user_id,
            reference=reference,
            candidates=[],
        )


def _normalize(value: str) -> str:
    normalized = _IGNORED_PUNCTUATION.sub('', value).casefold()
    for suffix in _REFERENCE_SUFFIXES:
        normalized_suffix = suffix.casefold()
        if (
            normalized.endswith(normalized_suffix)
            and len(normalized) > len(normalized_suffix)
        ):
            return normalized[: -len(normalized_suffix)]
    return normalized


def _is_keyword_match(reference: str, title: str) -> bool:
    normalized_reference = _normalize(reference)
    normalized_title = _normalize(title)
    if not normalized_reference or not normalized_title:
        return False
    return (
        normalized_reference in normalized_title
        or normalized_title in normalized_reference
    )


def _stable_task_key(task: Task) -> tuple[str, str]:
    return (_normalize(task.title), task.id)
