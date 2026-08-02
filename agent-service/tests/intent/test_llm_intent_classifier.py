import pytest

from app.intent.enums import IntentType
from app.intent.exceptions import (
    InvalidIntentOutputError,
    IntentProviderUnavailableError,
)
from app.intent.models import IntentRecognitionContext
from app.intent.providers.llm import LLMIntentClassifier


class FakeStructuredModel:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[object] = []

    async def ainvoke(self, input: object) -> object:
        self.calls.append(input)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.anyio
async def test_llm_provider_builds_prompt_from_context_and_validates_output() -> None:
    model = FakeStructuredModel(
        {'intent': 'QUERY_TASKS', 'confidence': 0.9, 'reason': '查询任务'}
    )
    contexts: list[IntentRecognitionContext] = []

    def prompt_builder(context: IntentRecognitionContext) -> list[str]:
        contexts.append(context)
        return [context.message]

    classifier = LLMIntentClassifier(model, prompt_builder)
    context = IntentRecognitionContext(message='今天有什么任务')

    result = await classifier.classify(context)

    assert result.intent == IntentType.QUERY_TASKS
    assert contexts == [context]
    assert model.calls == [['今天有什么任务']]


@pytest.mark.anyio
async def test_llm_provider_maps_invalid_output() -> None:
    classifier = LLMIntentClassifier(
        FakeStructuredModel({'intent': 'INVALID'}),
        lambda context: [context.message],
    )

    with pytest.raises(InvalidIntentOutputError):
        await classifier.classify(IntentRecognitionContext(message='test'))


@pytest.mark.anyio
async def test_llm_provider_maps_configured_supplier_error() -> None:
    classifier = LLMIntentClassifier(
        FakeStructuredModel(error=RuntimeError('supplier offline')),
        lambda context: [context.message],
        unavailable_exceptions=(RuntimeError,),
    )

    with pytest.raises(IntentProviderUnavailableError, match='RuntimeError'):
        await classifier.classify(IntentRecognitionContext(message='test'))


@pytest.mark.anyio
async def test_llm_provider_maps_timeout() -> None:
    classifier = LLMIntentClassifier(
        FakeStructuredModel(error=TimeoutError('slow provider')),
        lambda context: [context.message],
    )

    with pytest.raises(IntentProviderUnavailableError, match='TimeoutError'):
        await classifier.classify(IntentRecognitionContext(message='test'))


@pytest.mark.anyio
async def test_llm_provider_does_not_swallow_programming_errors() -> None:
    classifier = LLMIntentClassifier(
        FakeStructuredModel(error=KeyError('bug')),
        lambda context: [context.message],
    )

    with pytest.raises(KeyError):
        await classifier.classify(IntentRecognitionContext(message='test'))
