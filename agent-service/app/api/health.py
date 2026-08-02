from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import AppError

router = APIRouter(tags=['health'])


class HealthResponse(BaseModel):
    status: Literal['ok'] = 'ok'


@router.get('/health', response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse()


@router.get('/health/redis', response_model=HealthResponse)
async def get_redis_health(request: Request) -> HealthResponse:
    redis: Redis = request.app.state.redis
    try:
        healthy = await redis.ping()
    except RedisError as exc:
        raise AppError(
            'Redis is unavailable',
            code='redis_unavailable',
            status_code=503,
        ) from exc
    if not healthy:
        raise AppError(
            'Redis is unavailable',
            code='redis_unavailable',
            status_code=503,
        )
    return HealthResponse()
