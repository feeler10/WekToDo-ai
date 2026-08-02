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
    assert response.json() == {
        'error': {
            'code': 'redis_unavailable',
            'message': 'Redis is unavailable',
        }
    }
