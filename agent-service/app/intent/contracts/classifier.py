from typing import Protocol, runtime_checkable

from app.intent.models import IntentRecognitionContext, IntentResult


@runtime_checkable
class IntentClassifier(Protocol):
    async def classify(
        self,
        context: IntentRecognitionContext,
    ) -> IntentResult: ...
