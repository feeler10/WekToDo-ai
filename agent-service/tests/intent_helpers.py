from app.intent.enums import IntentType
from app.intent.models import IntentRecognitionContext, IntentResult
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.services.task_reference import parse_status_update


class ExistingFlowFakeIntentClassifier(FakeIntentClassifier):
    async def classify(
        self,
        context: IntentRecognitionContext,
    ) -> IntentResult:
        self.calls.append(context)
        message = context.message.strip()
        if any(
            marker in message
            for marker in ('查询', '查看', '哪些', '什么任务', '今日任务')
        ):
            return IntentResult(
                intent=IntentType.QUERY_TASKS,
                confidence=1,
                reason='测试查询意图',
            )
        try:
            update = parse_status_update(message)
        except ValueError:
            return IntentResult(
                intent=IntentType.CREATE_TASK,
                confidence=1,
                reason='测试创建意图',
            )
        return IntentResult(
            intent=IntentType.UPDATE_TASK_STATUS,
            confidence=1,
            reason='测试状态更新意图',
            task_reference=update.reference,
            target_status=update.target_status,
        )


def existing_flow_intent_service() -> IntentRecognitionService:
    return IntentRecognitionService(ExistingFlowFakeIntentClassifier())
