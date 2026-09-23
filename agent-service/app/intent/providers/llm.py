from collections.abc import Awaitable
from typing import Protocol

from langchain_core.exceptions import OutputParserException
from openai import APIError
from pydantic import ValidationError

from app.intent.exceptions import (
    InvalidIntentOutputError,
    IntentProviderUnavailableError,
)
from app.intent.models import IntentRecognitionContext, IntentResult
from app.intent.prompts import IntentPromptBuilder
from app.services.observability import execute_observed_model


class StructuredIntentModel(Protocol):
    def ainvoke(self, input: object) -> Awaitable[object]: ...


class LLMIntentClassifier:
    def __init__(
        self,
        structured_model: StructuredIntentModel,
        prompt_builder: IntentPromptBuilder,
        *,
        unavailable_exceptions: tuple[type[Exception], ...] = (
            APIError,
            TimeoutError,
        ),
    ) -> None:
        self._structured_model = structured_model
        self._prompt_builder = prompt_builder
        self._unavailable_exceptions = unavailable_exceptions

    async def classify(
        self,
        context: IntentRecognitionContext,
    ) -> IntentResult:
        messages = self._prompt_builder(context)
        try:
            output = await execute_observed_model(
                component='intent_classifier',
                attempt=1,
                input_payload={
                    'context': context,
                    'messages': messages,
                },
                operation=lambda: self._structured_model.ainvoke(messages),
            )
            return IntentResult.model_validate(output)
        except self._unavailable_exceptions as exc:
            raise IntentProviderUnavailableError(
                f'Intent provider unavailable: {type(exc).__name__}'
            ) from exc
        except (ValidationError, OutputParserException, TypeError, ValueError) as exc:
            raise InvalidIntentOutputError(
                f'Intent provider returned invalid output: {type(exc).__name__}'
            ) from exc
