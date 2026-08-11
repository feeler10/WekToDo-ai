from app.core.config import Settings
from app.graph.parser import StructuredOutputTaskParser
from app.graph.task_update_parser import StructuredOutputTaskUpdateParser
from app.graph.subtask_planner import StructuredOutputSubtaskPlanner
from app.services.llm_factory import create_chat_model


def create_task_parser(settings: Settings) -> StructuredOutputTaskParser:
    model = create_chat_model(
        settings,
        model_name=settings.llm_model,
        temperature=0,
    )

    return StructuredOutputTaskParser(
        lambda: model,
        method=settings.llm_structured_output_method,
        max_attempts=settings.task_parse_max_attempts,
    )


def create_task_update_parser(
    settings: Settings,
) -> StructuredOutputTaskUpdateParser:
    model = create_chat_model(
        settings,
        model_name=settings.llm_model,
        temperature=0,
    )
    return StructuredOutputTaskUpdateParser(
        lambda: model,
        method=settings.llm_structured_output_method,
        max_attempts=settings.task_parse_max_attempts,
    )


def create_subtask_planner(
    settings: Settings,
) -> StructuredOutputSubtaskPlanner:
    model = create_chat_model(
        settings,
        model_name=settings.llm_model,
        temperature=0,
    )
    return StructuredOutputSubtaskPlanner(
        lambda: model,
        method=settings.llm_structured_output_method,
        max_attempts=settings.task_parse_max_attempts,
    )
