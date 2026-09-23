from typing import Any, TypedDict


class TaskAgentState(TypedDict, total=False):
    user_id: str
    thread_id: str
    user_message: str
    timezone: str
    request_id: str
    trace_id: str
    parent_trace_id: str | None
    trace_operation: str

    intent: str
    intent_confidence: float
    intent_result: dict[str, Any]
    pending_route: str | None
    pending_query_clarification: dict[str, Any] | None
    pending_task_selection: dict[str, Any] | None
    pending_task_delete_selection: dict[str, Any] | None
    pending_task_draft_clarification: dict[str, Any] | None
    pending_task_update_clarification: dict[str, Any] | None
    active_task_context: dict[str, Any] | None
    task_collection_inputs: list[str]
    task_draft_clarification_round: int
    task_update_inputs: list[str]
    task_update_clarification_round: int


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
    parent_task: dict[str, Any] | None
    existing_subtasks: list[dict[str, Any]]
    subtask_plan_draft: dict[str, Any] | None
    subtask_plan: dict[str, Any] | None
    created_subtasks: list[dict[str, Any]]
    decomposition_message: str | None
    updated_task: dict[str, Any] | None
    deleted_task_id: str | None
    deleted_task_ids: list[str]
    deletion_tasks: list[dict[str, Any]]
    parent_tasks: list[dict[str, Any]]
    task_delete_parse_result: dict[str, Any] | None
    task_delete_route: str | None
    task_delete_selection_route: str | None
    resolved_delete_parent_id: str | None
    resolved_delete_references: dict[str, str]
    restored_from_cancelled: bool
    task_update_result: dict[str, Any] | None
    task_update: dict[str, Any] | None
    task_update_message: str | None

    final_response: str | None
    error: dict[str, Any] | None
    error_message: str | None
