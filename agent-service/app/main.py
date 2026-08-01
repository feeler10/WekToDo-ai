from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    application = FastAPI(
        title=app_settings.app_name,
        debug=app_settings.app_debug,
    )
    application.state.settings = app_settings
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_app()
