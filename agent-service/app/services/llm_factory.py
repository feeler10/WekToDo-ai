from langchain_openai import ChatOpenAI

from app.core.config import Settings


def create_chat_model(
    settings: Settings,
    *,
    model_name: str,
    temperature: float,
    max_tokens: int | None = None,
    enable_thinking: bool | None = None,
) -> ChatOpenAI:
    if not settings.llm_api_key:
        raise RuntimeError('LLM_API_KEY is required for model access')

    kwargs: dict[str, object] = {}
    if max_tokens is not None:
        kwargs['max_tokens'] = max_tokens
    if enable_thinking is not None:
        kwargs['extra_body'] = {'enable_thinking': enable_thinking}
    return ChatOpenAI(
        model=model_name,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature,
        **kwargs,
    )
