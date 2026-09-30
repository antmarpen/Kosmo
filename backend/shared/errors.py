from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorDetail:
    message_key: str
    params: dict[str, Any] = field(default_factory=dict)


class KosmoError(Exception):
    def __init__(self, message_key: str, params: dict[str, Any] | None = None,
                 details: list[ErrorDetail] | None = None, code: str = 'ERROR',
                 http_status: int = 400, internal: str | None = None) -> None:
        super().__init__(message_key)
        self.message_key = message_key
        self.params = params or {}
        self.details = details or []
        self.code = code
        self.http_status = http_status
        self.internal = internal


class AuthError(KosmoError):
    def __init__(self, message_key: str, params=None, details=None, code='AUTH_ERROR', internal=None):
        super().__init__(message_key, params, details, code, 401, internal)


class PermissionDeniedError(KosmoError):
    def __init__(self, message_key: str, params=None, details=None, code='PERMISSION_DENIED', internal=None):
        super().__init__(message_key, params, details, code, 403, internal)


class NotFoundError(KosmoError):
    def __init__(self, message_key: str, params=None, details=None, code='NOT_FOUND', internal=None):
        super().__init__(message_key, params, details, code, 404, internal)


class ConflictError(KosmoError):
    def __init__(self, message_key: str, params=None, details=None, code='CONFLICT', internal=None):
        super().__init__(message_key, params, details, code, 409, internal)


class ValidationFailedError(KosmoError):
    def __init__(self, message_key: str, params=None, details=None, code='VALIDATION_FAILED', internal=None):
        super().__init__(message_key, params, details, code, 422, internal)


class InternalError(KosmoError):
    def __init__(self, message_key: str = 'errors.internal', params=None, details=None, code='INTERNAL_ERROR', internal=None):
        super().__init__(message_key, params, details, code, 500, internal)
