from typing import Any
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import logger


class DocIntelException(Exception):
    """Base exception for DocIntel platform."""
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class TenantNotFoundError(DocIntelException):
    def __init__(self, message: str = "Organization not found"):
        super().__init__(message=message, status_code=status.HTTP_404_NOT_FOUND)


class AuthenticationFailedError(DocIntelException):
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class QuotaExceededError(DocIntelException):
    def __init__(self, message: str = "Monthly token budget exceeded for your organization"):
        super().__init__(message=message, status_code=status.HTTP_429_TOO_MANY_REQUESTS)


class ResourceNotFoundError(DocIntelException):
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            message=f"{resource} '{resource_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class AccessDeniedError(DocIntelException):
    def __init__(self, message: str = "Access forbidden to requested resource"):
        super().__init__(message=message, status_code=status.HTTP_403_FORBIDDEN)


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on FastAPI application."""

    @app.exception_handler(DocIntelException)
    async def docintel_exception_handler(request: Request, exc: DocIntelException):
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.__class__.__name__,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        from fastapi.encoders import jsonable_encoder
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "ValidationError",
                    "message": "Request payload validation failed",
                    "details": jsonable_encoder(exc.errors()),
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        request_id = getattr(request.state, "request_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "HTTPException",
                    "message": exc.detail,
                    "request_id": request_id,
                }
            },
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        logger.exception("unhandled_server_error", extra={"request_id": request_id})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "InternalServerError",
                    "message": "An unexpected server error occurred. Please try again later.",
                    "request_id": request_id,
                }
            },
        )
