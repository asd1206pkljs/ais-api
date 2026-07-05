from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import settings
from app.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InsufficientCreditsError,
    NotFoundError,
    ValidationError,
)


def _make_response(request: Request, status: int, error: str) -> JSONResponse:
    response = JSONResponse(
        status_code=status,
        content={"success": False, "data": None, "error": error, "metadata": None},
    )
    origin = request.headers.get("origin", "")
    if origin in settings.cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


def setup_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        return _make_response(request, 404, str(exc))

    @app.exception_handler(AuthenticationError)
    async def auth_error_handler(request: Request, exc: AuthenticationError):
        return _make_response(request, 401, str(exc))

    @app.exception_handler(AuthorizationError)
    async def authz_error_handler(request: Request, exc: AuthorizationError):
        return _make_response(request, 403, str(exc))

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError):
        return _make_response(request, 409, str(exc))

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError):
        return _make_response(request, 422, str(exc))

    @app.exception_handler(InsufficientCreditsError)
    async def insufficient_credits_handler(request: Request, exc: InsufficientCreditsError):
        return _make_response(request, 402, str(exc))

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        errors = "; ".join(
            f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return _make_response(request, 422, errors)

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception):
        return _make_response(request, 500, "Internal server error")
