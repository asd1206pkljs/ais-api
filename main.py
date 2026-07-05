from fastapi import FastAPI

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


def create_app() -> FastAPI:
    app = FastAPI(
        title="AIS Equipment Layout API",
        description="API server for semiconductor equipment layout management",
        version="1.0.0",
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
