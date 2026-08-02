import logging

from pydantic import ValidationError

from app.intent.contracts import IntentClassifier
from app.intent.enums import IntentType
from app.intent.exceptions import IntentRecognitionError
from app.intent.models import IntentRecognitionContext, IntentResult
from app.intent.query_validation import validate_query_completeness

logger = logging.getLogger(__name__)


class IntentRecognitionService:
    def __init__(self, classifier: IntentClassifier) -> None:
        self._classifier = classifier

    async def recognize(
        self,
        context: IntentRecognitionContext,
    ) -> IntentResult:
        if not context.message.strip():
            return self._empty_input_result()
        try:
            result = await self._classifier.classify(context)
            validated = IntentResult.model_validate(result)
            return validate_query_completeness(validated, context)
        except (IntentRecognitionError, ValidationError) as exc:
            logger.warning('Intent recognition failed: %s', type(exc).__name__)
            return self._fallback_result()

    @staticmethod
    def _empty_input_result() -> IntentResult:
        return IntentResult(
            intent=IntentType.UNKNOWN,
            confidence=0,
            reason='用户输入为空',
            needs_clarification=True,
            clarification_question=(
                '请输入你想创建、查询、修改、完成或拆解的任务。'
            ),
        )

    @staticmethod
    def _fallback_result() -> IntentResult:
        return IntentResult(
            intent=IntentType.UNKNOWN,
            confidence=0,
            reason='意图识别服务暂时不可用',
            needs_clarification=False,
        )
