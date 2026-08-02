from typing import Protocol

from pydantic import BaseModel

from app.core.config import Settings
from app.intent.contracts import IntentClassifier
from app.intent.enums import IntentClassifierProvider
from app.intent.exceptions import UnsupportedIntentProviderError
from app.intent.models import IntentResult
from app.intent.prompts import build_intent_messages
from app.intent.providers.llm import LLMIntentClassifier, StructuredIntentModel
from app.intent.service import IntentRecognitionService
from app.services.llm_factory import create_chat_model


class StructuredOutputCapableModel(Protocol):
    def with_structured_output(
        self,
        schema: type[BaseModel],
        **kwargs: object,
    ) -> StructuredIntentModel: ...


def create_intent_classifier(
    settings: Settings,
    *,
    chat_model: StructuredOutputCapableModel | None = None,
) -> IntentClassifier:
    provider = settings.intent_classifier_provider
    if provider != IntentClassifierProvider.LLM:
        raise UnsupportedIntentProviderError(
            f'Intent provider is not implemented: {provider.value}'
        )

    model = chat_model or create_chat_model(
        settings,
        model_name=settings.intent_model_name,
        temperature=settings.intent_model_temperature,
        max_tokens=settings.intent_model_max_tokens,
        enable_thinking=settings.intent_model_enable_thinking,
    )
    structured_model = model.with_structured_output(
        IntentResult,
        method=settings.llm_structured_output_method,
    )
    return LLMIntentClassifier(structured_model, build_intent_messages)


def create_intent_service(
    settings: Settings,
    *,
    chat_model: StructuredOutputCapableModel | None = None,
) -> IntentRecognitionService:
    return IntentRecognitionService(
        create_intent_classifier(settings, chat_model=chat_model)
    )
