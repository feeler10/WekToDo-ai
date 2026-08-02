import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return 'asyncio'


@pytest.fixture
def client() -> TestClient:
    settings = Settings(app_env='test')
    with TestClient(create_app(settings)) as test_client:
        yield test_client
