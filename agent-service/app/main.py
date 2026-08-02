from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.storage.redis_client import create_redis_client
from app.storage.redis_checkpoint import create_redis_checkpointer
from app.graph.builder import GraphDependencies, build_task_graph
from app.repositories.redis_task import RedisTaskRepository
from app.services.agent import TaskAgentService
from app.services.parser_factory import create_task_parser


def create_app(
    settings: Settings | None = None,
    redis_client: Redis | None = None,
    agent_service: TaskAgentService | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owns_redis_client = redis_client is None
        application.state.redis = (
            redis_client
            if redis_client is not None
            else create_redis_client(app_settings.redis_url)
        )
        application.state.agent_service = agent_service
        try:
            if agent_service is not None or app_settings.app_env == 'test':
                yield
            else:
                async with create_redis_checkpointer(
                    app_settings.checkpoint_redis_url
                ) as checkpointer:
                    await checkpointer.asetup()
                    repository = RedisTaskRepository(application.state.redis)
                    graph = build_task_graph(
                        GraphDependencies(
                            parser=create_task_parser(app_settings),
                            task_repository=repository,
                        ),
                        checkpointer=checkpointer,
                    )
                    application.state.agent_service = TaskAgentService(graph)
                    yield
        finally:
            if owns_redis_client:
                await application.state.redis.aclose()

    application = FastAPI(
        title=app_settings.app_name,
        debug=app_settings.app_debug,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
