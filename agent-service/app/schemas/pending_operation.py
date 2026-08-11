from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class PendingOperationContextBase(BaseModel):
    """Shared persistence and isolation envelope for one pending operation."""

    model_config = ConfigDict(extra='forbid')

    user_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    user_inputs: list[str] = Field(min_length=1, max_length=8)
    clarification_question: str = Field(min_length=1, max_length=300)
    clarification_round: int = Field(ge=1, le=20)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator('user_inputs')
    @classmethod
    def normalize_user_inputs(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError('user_inputs cannot contain empty values')
        if any(len(item) > 2000 for item in normalized):
            raise ValueError(
                'each user input must contain at most 2000 characters'
            )
        return normalized

    @model_validator(mode='after')
    def validate_expiration(self) -> 'PendingOperationContextBase':
        if self.expires_at <= self.created_at:
            raise ValueError('expires_at must be later than created_at')
        return self
