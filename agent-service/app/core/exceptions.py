import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = 'application_error',
        status_code: int = 400,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    trace_id = getattr(_request.state, 'trace_id', None)
    error: dict[str, Any] = {
        'code': exc.code,
        'message': exc.message,
        'trace_id': trace_id,
    }
    if exc.details is not None:
        error['details'] = jsonable_encoder(exc.details)
    return JSONResponse(
        status_code=exc.status_code,
        content={'error': error},
        headers=_trace_headers(trace_id),
    )


async def handle_validation_error(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    details = [
        {'location': list(error['loc']), 'type': error['type']}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            'error': {
                'code': 'validation_error',
                'message': '请求参数不正确，请检查后重试。',
                'trace_id': getattr(request.state, 'trace_id', None),
                'details': jsonable_encoder(details),
            }
        },
        headers=_trace_headers(getattr(request.state, 'trace_id', None)),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        'Unhandled exception while processing %s %s',
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            'error': {
                'code': 'internal_server_error',
                'message': '系统处理失败，请稍后重试并提供追踪编号。',
                'trace_id': getattr(request.state, 'trace_id', None),
            }
        },
        headers=_trace_headers(getattr(request.state, 'trace_id', None)),
    )


def _trace_headers(trace_id: str | None) -> dict[str, str]:
    return {'X-Trace-Id': trace_id} if trace_id else {}


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
