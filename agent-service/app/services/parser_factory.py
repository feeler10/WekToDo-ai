from langchain_openai import ChatOpenAI

from app.core.config import Settings
from app.graph.parser import StructuredOutputTaskParser


def create_task_parser(settings: Settings) -> StructuredOutputTaskParser:
    def model_factory() -> ChatOpenAI:
        if not settings.llm_api_key:
            raise RuntimeError('LLM_API_KEY is required for task parsing')
        return ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0,
        )

    return StructuredOutputTaskParser(
        model_factory,
        method=settings.llm_structured_output_method,
        max_attempts=settings.task_parse_max_attempts,
    )
