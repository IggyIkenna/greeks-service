"""greeks-service — FastAPI health API.

Exposes /health and /readiness via UTL ``make_health_router`` with a ``data_freshness``
callback. HTTP lifecycle (STARTED / STOPPED / FAILED) uses ``fastapi_uei_lifespan`` —
same sink rules as ``ServiceBootstrap`` for CLI mode (QG STEP 5.62).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from unified_trading_library import (
    fastapi_uei_lifespan,
    make_health_router,
)

_SERVICE_NAME = "greeks-service"
_SERVICE_VERSION = "0.1.0"

_last_processed_date: date | None = None


def set_last_processed_date(d: date) -> None:
    """Set last processed date — called by greeks-computation pipeline post-write."""
    global _last_processed_date
    _last_processed_date = d


def _data_freshness() -> dict[str, object]:
    """data_freshness callback for make_health_router (QG STEP 5.62)."""
    if _last_processed_date is None:
        return {"last_processed_date": None, "stale": True}
    return {"last_processed_date": _last_processed_date.isoformat(), "stale": False}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    async with fastapi_uei_lifespan(
        _SERVICE_NAME,
        entrypoint="greeks_service.api.main",
    ):
        yield


def create_app() -> FastAPI:
    """Create the FastAPI app — wired into uvicorn via the Dockerfile CMD."""
    app = FastAPI(
        title=_SERVICE_NAME,
        version=_SERVICE_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=_lifespan,
    )
    health_router = make_health_router(
        service_name=_SERVICE_NAME,
        version=_SERVICE_VERSION,
        data_freshness=_data_freshness,
    )
    app.include_router(health_router)
    return app


app = create_app()
