import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shared.errors import KosmoError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's default `input` fields can echo large/user-authored bodies.
        # Keep diagnostics bounded to structural locations and error types.
        details = []
        for error in exc.errors()[:20]:
            loc = [str(part)[:80] for part in error.get('loc', ())[:8]]
            details.append({'message_key': 'errors.request.invalid',
                            'params': {'location': loc, 'type': str(error.get('type', 'invalid'))[:80]}})
        return JSONResponse(status_code=422, content={
            'code': 'VALIDATION_FAILED', 'message_key': 'errors.request.invalid',
            'params': {}, 'details': details,
        })

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
