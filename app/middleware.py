import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import Response

from app.config import settings
from app.services.audit_context import RequestContext, reset, set_request_context

# DISABLE_RATE_LIMIT=true turns the per-IP limiter off (tests / local tooling only).
limiter = Limiter(key_func=get_remote_address, enabled=not settings.DISABLE_RATE_LIMIT)


def _cors_aware_handler(request: Request, response: Response) -> Response:
    origin = request.headers.get("origin", "")
    if origin in settings.cors_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


def setup_middleware(app: FastAPI) -> None:
    app.state.limiter = limiter

    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        response = JSONResponse(
            status_code=429,
            content={"success": False, "data": None, "error": "Too many requests", "metadata": None},
        )
        return _cors_aware_handler(request, response)

    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        set_request_context(RequestContext(
            request_id=request_id,
            ip_address=get_remote_address(request),
            user_agent=request.headers.get("user-agent"),
        ))
        try:
            response = await call_next(request)
        finally:
            reset()
        response.headers["X-Request-ID"] = request_id
        return response
