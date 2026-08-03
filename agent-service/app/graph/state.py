from typing import Any, TypedDict


class TaskAgentState(TypedDict, total=False):
    user_id: str
    thread_id: str
    user_message: str
    timezone: str
    request_id: str

    intent: str
    intent_confidence: float
    intent_result: dict[str, Any]
    pending_route: str | None
    pending_query_clarification: dict[str, Any] | None
    pending_task_selection: dict[str, Any] | None


    parsed_task: dict[str, Any] | None
    task_draft: dict[str, Any] | None
    priority_factors: dict[str, int]
    missing_fields: list[str]
    validation_errors: list[str]
    validation_passed: bool

    urgency_score: int | None
    ai_priority: str | None
    priority_reason: str | None

    pending_action: dict[str, Any] | None
    confirmation_round: int
    confirmation_status: str | None
    review_action: str | None
    last_handled_action_id: str | None
    regeneration_feedback: str | None
    user_priority: str | None
    created_task: dict[str, Any] | None
    query_kind: str | None
    task_query_plan: dict[str, Any] | None
    task_reference: str | None
    target_status: str | None
    task_results: list[dict[str, Any]]
    candidate_tasks: list[dict[str, Any]]
    selected_task: dict[str, Any] | None
    updated_task: dict[str, Any] | None

    final_response: str | None
    error_message: str | None
