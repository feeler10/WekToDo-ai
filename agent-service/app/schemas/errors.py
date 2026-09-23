from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentErrorInfo(BaseModel):
    model_config = ConfigDict(extra='forbid')

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    details: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, min_length=1, max_length=100)
