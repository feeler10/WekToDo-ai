from collections.abc import Mapping

from app.intent.exceptions import InvalidIntentOutputError
from app.intent.models import IntentRecognitionContext, IntentResult


class FakeIntentClassifier:
    def __init__(
        self,
        result: IntentResult | Mapping[str, object] | None = None,
        *,
        responses: Mapping[
            str,
            IntentResult | Mapping[str, object],
        ] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._responses = dict(responses or {})
        self._error = error
        self.calls: list[IntentRecognitionContext] = []

    async def classify(
        self,
        context: IntentRecognitionContext,
    ) -> IntentResult:
        self.calls.append(context)
        if self._error is not None:
            raise self._error
        candidate = self._responses.get(context.message, self._result)
        if candidate is None:
            raise InvalidIntentOutputError(
                f'No fake intent result configured for message: {context.message}'
            )
        return IntentResult.model_validate(candidate)
