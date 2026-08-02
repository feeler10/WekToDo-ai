from app.graph.state import TaskAgentState
from app.intent.enums import IntentType
from app.intent.models import IntentResult


def request_intent_clarification(
    state: TaskAgentState,
) -> dict[str, object]:
    result = IntentResult.model_validate(state.get('intent_result'))
    return {
        'final_response': result.clarification_question,
        'error_message': None,
    }


def respond_to_general_chat(state: TaskAgentState) -> dict[str, object]:
    return {
        'final_response': (
            '你好！我可以帮你创建、查询、修改、完成或拆解任务。'
        ),
        'error_message': None,
    }


def respond_feature_unavailable(state: TaskAgentState) -> dict[str, object]:
    intent = IntentType(state['intent'])
    feature = (
        '任务属性修改'
        if intent == IntentType.UPDATE_TASK
        else '任务拆解'
    )
    return {
        'final_response': f'{feature}功能暂未开放。',
        'error_message': None,
    }


def respond_unknown_intent(state: TaskAgentState) -> dict[str, object]:
    result = IntentResult.model_validate(state.get('intent_result'))
    message = (
        '意图识别服务暂时不可用，请稍后重试。'
        if result.reason == '意图识别服务暂时不可用'
        else '暂时无法识别你的操作，请换一种说法。'
    )
    return {'final_response': message, 'error_message': None}
