from pydantic import BaseModel, ConfigDict, Field

from app.schemas.task import TaskPriority


class UrgencyFactors(BaseModel):
    model_config = ConfigDict(extra='forbid')

    deadline_score: int = Field(ge=0, le=100)
    semantic_importance: int = Field(ge=0, le=100)
    impact_score: int = Field(ge=0, le=100)
    workload_risk_score: int = Field(ge=0, le=100)
    dependency_score: int = Field(ge=0, le=100)


class UrgencyResult(BaseModel):
    model_config = ConfigDict(extra='forbid')

    urgency_score: int = Field(ge=0, le=100)
    priority: TaskPriority
