from langgraph.types import interrupt
from pydantic import ValidationError

from app.graph.state import TaskAgentState
from app.schemas.agent import ConfirmationAction, ConfirmationDecision
from app.schemas.audit import PendingAction
from app.schemas.subtask import SubtaskPlanEdit


def request_confirmation(state: TaskAgentState) -> dict[str, object]:
    pending = PendingAction.model_validate(state.get('pending_action'))
    allowed_actions = (
        [ConfirmationAction.APPROVE, ConfirmationAction.REJECT]
        if pending.action_type in {
            'update_task_status',
            'update_task',
            'delete_task',
            'delete_tasks_batch',
            'restore_task',
        }
        else list(ConfirmationAction)
    )
    response = interrupt(
        {
            'type': (
                'subtask_plan_confirmation'
                if pending.action_type == 'create_subtasks_batch'
                else (
                    'task_delete_confirmation'
                    if pending.action_type in {'delete_task', 'delete_tasks_batch'}
                    else (
                        'task_restore_confirmation'
                        if pending.action_type == 'restore_task'
                        else 'task_confirmation'
                    )
                )
            ),
            'pending_action': pending.model_dump(mode='json'),
            'allowed_actions': [action.value for action in allowed_actions],
        }
    )
    try:
        decision = ConfirmationDecision.model_validate(response)
    except ValidationError as exc:
        return {'error_message': f'Invalid confirmation response: {exc}'}

    if decision.action_id != pending.id:
        return {'error_message': 'Confirmation action_id does not match pending action'}
    if decision.action not in allowed_actions:
        return {'error_message': 'Confirmation action is not allowed'}

    update: dict[str, object] = {
        'review_action': decision.action.value,
        'last_handled_action_id': pending.id,
        'error_message': None,
    }
    if decision.action == ConfirmationAction.APPROVE:
        update['confirmation_status'] = 'approved'
        update['pending_action'] = pending.model_copy(
            update={'confirmation_status': 'approved'}
        ).model_dump(mode='json')
    elif decision.action == ConfirmationAction.REJECT:
        update['confirmation_status'] = 'rejected'
        update['pending_action'] = pending.model_copy(
            update={'confirmation_status': 'rejected'}
        ).model_dump(mode='json')
        if pending.action_type == 'update_task_status':
            update['final_response'] = '已取消任务状态更新。'
        elif pending.action_type == 'update_task':
            update['final_response'] = '已取消任务属性修改。'
        elif pending.action_type == 'create_subtasks_batch':
            update['final_response'] = '已取消任务拆解和子任务创建。'
        elif pending.action_type == 'delete_task':
            update['final_response'] = '已取消删除任务。'
        elif pending.action_type == 'delete_tasks_batch':
            update['final_response'] = '已取消批量删除任务。'
        elif pending.action_type == 'restore_task':
            update['final_response'] = '已取消恢复任务，原操作未执行。'
        else:
            update['final_response'] = '已取消创建任务。'
    elif decision.action == ConfirmationAction.EDIT:
        edits = decision.edits
        assert edits is not None
        if pending.action_type == 'create_subtasks_batch':
            if not isinstance(edits, SubtaskPlanEdit):
                return {'error_message': '批量子任务编辑必须提交完整拆解方案'}
            update['subtask_plan_draft'] = edits.model_dump(mode='json')
            update['subtask_plan'] = None
        else:
            if isinstance(edits, SubtaskPlanEdit):
                return {'error_message': '任务编辑不能使用子任务方案格式'}
            draft_updates = edits.model_dump(
                mode='json',
                exclude_unset=True,
                exclude={'user_priority'},
            )
            update['task_draft'] = {
                **(state.get('task_draft') or {}),
                **draft_updates,
            }
            if 'user_priority' in edits.model_fields_set:
                update['user_priority'] = (
                    edits.user_priority.value if edits.user_priority else None
                )
        update['confirmation_status'] = 'cancelled'
        update['pending_action'] = pending.model_copy(
            update={'confirmation_status': 'cancelled'}
        ).model_dump(mode='json')
    else:
        update['confirmation_status'] = 'cancelled'
        update['pending_action'] = pending.model_copy(
            update={'confirmation_status': 'cancelled'}
        ).model_dump(mode='json')
        update['regeneration_feedback'] = decision.feedback

    return update
