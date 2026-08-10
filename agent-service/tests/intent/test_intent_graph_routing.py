from pathlib import Path

import pytest

from app.graph.routing import route_after_classification
from app.intent.enums import IntentType


@pytest.mark.parametrize(
    ('intent', 'expected'),
    [
        (IntentType.CREATE_TASK, 'parse_task'),
        (IntentType.QUERY_TASKS, 'query_task_data'),
        (IntentType.UPDATE_TASK_STATUS, 'resolve_task_reference'),
        (IntentType.UPDATE_TASK, 'resolve_task_reference'),
        (IntentType.DECOMPOSE_TASK, 'respond_feature_unavailable'),
        (IntentType.GENERAL_CHAT, 'respond_to_general_chat'),
        (IntentType.UNKNOWN, 'respond_unknown_intent'),
    ],
)
def test_each_intent_routes_without_provider_branching(
    intent: IntentType,
    expected: str,
) -> None:
    state = {
        'intent': intent.value,
        'intent_result': {'needs_clarification': False},
    }

    assert route_after_classification(state) == expected


def test_clarification_has_priority_over_write_route() -> None:
    state = {
        'intent': IntentType.UPDATE_TASK_STATUS.value,
        'intent_result': {'needs_clarification': True},
    }

    assert route_after_classification(state) == 'request_intent_clarification'


def test_graph_layer_does_not_import_concrete_provider() -> None:
    graph_root = Path(__file__).resolve().parents[2] / 'app' / 'graph'
    sources = '\n'.join(
        path.read_text(encoding='utf-8')
        for path in graph_root.rglob('*.py')
    )

    assert 'app.intent.providers' not in sources
    assert 'LLMIntentClassifier' not in sources
