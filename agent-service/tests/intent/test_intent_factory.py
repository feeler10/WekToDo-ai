import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.intent.enums import IntentClassifierProvider, IntentType
from app.intent.exceptions import UnsupportedIntentProviderError
from app.intent.factory import create_intent_classifier, create_intent_service
from app.intent.models import IntentRecognitionContext
from app.intent.providers.llm import LLMIntentClassifier


class FakeRunnable:
    async def ainvoke(self, input: object) -> object:
        return {'intent': 'GENERAL_CHAT', 'confidence': 1, 'reason': '问候'}


class FakeChatModel:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def with_structured_output(
        self,
        schema: object,
        **kwargs: object,
    ) -> FakeRunnable:
        self.calls.append((schema, kwargs))
        return FakeRunnable()


@pytest.mark.anyio
async def test_llm_factory_builds_structured_model_only_once() -> None:
    settings = Settings(app_env='test', _env_file=None)
    model = FakeChatModel()
    classifier = create_intent_classifier(settings, chat_model=model)

    assert isinstance(classifier, LLMIntentClassifier)
    await classifier.classify(IntentRecognitionContext(message='你好'))
    await classifier.classify(IntentRecognitionContext(message='你好'))
    assert len(model.calls) == 1
    assert model.calls[0][1] == {'method': 'json_mode'}


@pytest.mark.anyio
async def test_factory_builds_service_using_selected_provider() -> None:
    service = create_intent_service(
        Settings(app_env='test', _env_file=None),
        chat_model=FakeChatModel(),
    )

    result = await service.recognize(IntentRecognitionContext(message='你好'))

    assert result.intent == IntentType.GENERAL_CHAT


@pytest.mark.parametrize(
    'provider',
    [
        IntentClassifierProvider.RULE,
        IntentClassifierProvider.SEMANTIC,
        IntentClassifierProvider.HYBRID,
    ],
)
def test_unimplemented_provider_fails_explicitly(
    provider: IntentClassifierProvider,
) -> None:
    settings = Settings(
        app_env='test',
        intent_classifier_provider=provider,
        _env_file=None,
    )

    with pytest.raises(UnsupportedIntentProviderError, match=provider.value):
        create_intent_classifier(settings, chat_model=FakeChatModel())


def test_invalid_provider_fails_settings_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env='test',
            intent_classifier_provider='fake',
            _env_file=None,
        )
