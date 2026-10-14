import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.config import settings
from app.exception_handlers import setup_exception_handlers
from app.middleware import setup_middleware
from app.routers import (
    auth,
    contact,
    equipment,
    flow_recipes,
    jobs,
    modules,
    process_recipes,
    simulators,
    users,
)
from app.tasks.cleanup import start_background_cleanup


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Hourly purge of expired pending sign-ups, revoked tokens and lockout counters.
    cleanup = start_background_cleanup() if settings.ENABLE_BACKGROUND_CLEANUP else None
    try:
        yield
    finally:
        if cleanup is not None:
            cleanup.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup


def create_app() -> FastAPI:
    app = FastAPI(
        title="AIS Equipment Layout API",
        description="API server for semiconductor equipment layout management",
        version="1.0.0",
        lifespan=lifespan,
    )

    setup_middleware(app)
    setup_exception_handlers(app)

    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(jobs.router)
    app.include_router(equipment.router)
    app.include_router(modules.router)
    app.include_router(flow_recipes.router)
    app.include_router(process_recipes.router)
    app.include_router(simulators.router)
    app.include_router(contact.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
