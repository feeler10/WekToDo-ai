from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app.core.config import Settings
from app.main import create_app


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get('/health')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_redis_health_returns_ok() -> None:
    redis = AsyncMock()
    redis.ping.return_value = True

    with TestClient(create_app(Settings(app_env='test'), redis)) as client:
        response = client.get('/health/redis')

    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
    redis.ping.assert_awaited_once()


def test_redis_health_returns_503_when_unavailable() -> None:
    redis = AsyncMock()
    redis.ping.side_effect = ConnectionError('unavailable')

    with TestClient(create_app(Settings(app_env='test'), redis)) as client:
        response = client.get('/health/redis')

    assert response.status_code == 503
    error = response.json()['error']
    assert error['code'] == 'redis_unavailable'
    assert error['message'] == '任务存储暂时不可用，请稍后重试。'
    assert error['trace_id'] == response.headers['X-Trace-Id']


def test_validation_error_is_chinese_and_does_not_expose_internal_message() -> None:
    with TestClient(create_app(Settings(app_env='test'))) as client:
        response = client.post('/api/agent/chat', json={})

    assert response.status_code == 422
    error = response.json()['error']
    assert error['code'] == 'validation_error'
    assert error['message'] == '请求参数不正确，请检查后重试。'
    assert error['trace_id'] == response.headers['X-Trace-Id']
    assert all('msg' not in detail for detail in error['details'])


def test_unexpected_error_is_chinese_and_does_not_leak_exception() -> None:
    app = create_app(Settings(app_env='test'))

    @app.get('/test/unexpected')
    async def unexpected() -> None:
        raise RuntimeError('secret internal failure')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/test/unexpected')

    assert response.status_code == 500
    error = response.json()['error']
    assert error['message'] == '系统处理失败，请稍后重试并提供追踪编号。'
    assert 'secret internal failure' not in response.text
    assert error['trace_id'] == response.headers['X-Trace-Id']
