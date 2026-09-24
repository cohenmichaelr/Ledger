"""App entry point. Run with:  uv run uvicorn ledger.main:app --reload"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ledger.api import health, trades
from ledger.db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Dev convenience: create tables on startup. We'll switch to Alembic migrations in Week 2.
    Base.metadata.create_all(engine)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Ledger", version="0.1.0", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(trades.router)
    return app


app = create_app()
