from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.matching.models import TaskMatchResult
from app.schemas.task import Task


class TaskMatcher(ABC):
    @abstractmethod
    def match(
        self,
        *,
        reference: str,
        user_id: str,
        tasks: Sequence[Task],
    ) -> TaskMatchResult:
        """Return deterministic candidates belonging to user_id."""

        raise NotImplementedError
