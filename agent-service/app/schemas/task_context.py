from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ActiveTaskContext(BaseModel):
    """Short-lived pointer to the single task currently in focus."""

    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    updated_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode='after')
    def require_future_expiration(self) -> 'ActiveTaskContext':
        if self.expires_at <= self.updated_at:
            raise ValueError('expires_at must be later than updated_at')
        return self
