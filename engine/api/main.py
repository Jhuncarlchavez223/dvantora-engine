"""FastAPI application (05-api-contract.md).

Local development only: no Supabase, no Railway, no vendor calls, no model calls.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from engine.api.routes import meta, runs
from engine.config import settings
from engine.errors import ApiError

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.getLogger("dvantora").info(
        "engine starting env=%s collector_mode=%s ai_provider=%s",
        settings.env,
        settings.collector_mode,
        settings.ai_provider,
    )
    yield


app = FastAPI(title="Dvantora Engine", version="0.1.0", docs_url="/docs", lifespan=lifespan)

API_PREFIX = "/api/v1"
app.include_router(meta.router, prefix=API_PREFIX)
app.include_router(runs.router, prefix=API_PREFIX)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body())
