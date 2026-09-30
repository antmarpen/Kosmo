import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from shared.errors import KosmoError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(KosmoError)
    async def handle_kosmo_error(request: Request, exc: KosmoError) -> JSONResponse:
        if exc.internal:
            logger.error('KosmoError internal details', extra={
                'message_key': exc.message_key, 'code': exc.code, 'internal': exc.internal,
            }, stack_info=True)
        return JSONResponse(status_code=exc.http_status, content={
            'code': exc.code, 'message_key': exc.message_key, 'params': exc.params,
            'details': [{'message_key': detail.message_key, 'params': detail.params} for detail in exc.details],
        })

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error('Unhandled application exception', exc_info=(type(exc), exc, exc.__traceback__))
        return JSONResponse(status_code=500, content={
            'code': 'INTERNAL_ERROR', 'message_key': 'errors.internal', 'params': {}, 'details': [],
        })
