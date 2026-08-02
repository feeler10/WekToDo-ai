from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class TaskDraft(BaseModel):
    model_config = ConfigDict(extra='forbid')

    title: str = Field(min_length=1, max_length=200)
    description: str = ''
    category: str | None = None
    deadline: AwareDatetime | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)
    semantic_importance: int = Field(default=0, ge=0, le=100)
    impact_score: int = Field(default=0, ge=0, le=100)
    deadline_score: int = Field(default=0, ge=0, le=100)
    workload_risk_score: int = Field(default=0, ge=0, le=100)
    dependency_score: int = Field(default=0, ge=0, le=100)
    priority_reason: str | None = None
