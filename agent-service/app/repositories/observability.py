from abc import ABC, abstractmethod

from app.schemas.audit import ToolExecutionLog
from app.schemas.trace import TraceEvent, TraceRecord


class ObservabilityRepository(ABC):
    @abstractmethod
    async def start_trace(self, trace: TraceRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    async def finish_trace(self, trace: TraceRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    async def append_trace_event(self, event: TraceEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    async def start_tool_execution(self, log: ToolExecutionLog) -> None:
        raise NotImplementedError

    @abstractmethod
    async def finish_tool_execution(self, log: ToolExecutionLog) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_trace(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> TraceRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def list_trace_events(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> list[TraceEvent]:
        raise NotImplementedError

    @abstractmethod
    async def list_tool_executions(
        self,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> list[ToolExecutionLog]:
        raise NotImplementedError
