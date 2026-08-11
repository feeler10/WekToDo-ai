from collections.abc import Mapping
from typing import Any

import pytest

from app.graph.builder import GraphDependencies, build_task_graph
from app.intent.enums import IntentType
from app.intent.exceptions import IntentProviderUnavailableError
from app.intent.models import IntentResult
from app.intent.providers.fake import FakeIntentClassifier
from app.intent.service import IntentRecognitionService
from app.schemas.task import TaskStatus


class UnusedParser:
    async def parse(
        self,
        user_message: str,
        *,
        timezone: str,
    ) -> Mapping[str, Any]:
        raise AssertionError('task parser must not be called')


class ExplodingRepository:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f'repository must not be accessed: {name}')


def _state(message: str) -> dict[str, str]:
    return {
        'user_id': 'user-1',
        'thread_id': 'thread-1',
        'request_id': 'request-1',
        'user_message': message,
        'timezone': 'Asia/Shanghai',
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ('intent', 'expected_message'),
    [
        (
            IntentType.GENERAL_CHAT,
            '你好！我可以帮你创建、查询、修改、完成、拆解或删除任务。',
        ),
        (
            IntentType.UPDATE_TASK,
            'Task reference resolution failed: '
            'repository must not be accessed: list_tasks',
        ),
        (
            IntentType.DECOMPOSE_TASK,
            '你想拆解哪个任务？请告诉我任务名称。',
        ),
    ],
)
async def test_switching_fake_result_changes_route_without_graph_changes(
    intent: IntentType,
    expected_message: str,
) -> None:
    service = IntentRecognitionService(
        FakeIntentClassifier(
            IntentResult(intent=intent, confidence=1, reason='测试路由')
        )
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedParser(),
            intent_service=service,
            task_repository=ExplodingRepository(),
        )
    )

    result = await graph.ainvoke(_state('同一上层调用'))

    assert result['intent'] == intent.value
    assert result['final_response'] == expected_message


@pytest.mark.anyio
async def test_clarification_result_stops_before_repository_access() -> None:
    intent_result = IntentResult(
        intent=IntentType.UPDATE_TASK_STATUS,
        confidence=0.9,
        reason='缺少任务引用',
        target_status=TaskStatus.DONE,
        needs_clarification=True,
        clarification_question='你想标记完成的是哪个任务？',
    )
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedParser(),
            intent_service=IntentRecognitionService(
                FakeIntentClassifier(intent_result)
            ),
            task_repository=ExplodingRepository(),
        )
    )

    result = await graph.ainvoke(_state('把它标记完成'))

    assert result['intent'] == IntentType.UPDATE_TASK_STATUS.value
    assert result['final_response'] == '你想标记完成的是哪个任务？'
    assert result.get('pending_action') is None


@pytest.mark.anyio
async def test_provider_failure_routes_to_retry_without_write_path() -> None:
    graph = build_task_graph(
        GraphDependencies(
            parser=UnusedParser(),
            intent_service=IntentRecognitionService(
                FakeIntentClassifier(
                    error=IntentProviderUnavailableError('offline')
                )
            ),
            task_repository=ExplodingRepository(),
        )
    )

    result = await graph.ainvoke(_state('完成任务'))

    assert result['intent'] == IntentType.UNKNOWN.value
    assert result['final_response'] == '意图识别服务暂时不可用，请稍后重试。'
    assert result.get('pending_action') is None
