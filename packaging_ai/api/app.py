from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from packaging_ai import __version__
from packaging_ai.api.auth import require_api_key
from packaging_ai.api.jobs import router as jobs_router
from packaging_ai.api.repository import get_repository
from packaging_ai.api.schemas import HealthResponse
from packaging_ai.api.worker import get_worker
from packaging_ai.config import API_KEYS, JOB_STORE, LOG_FILE, LOG_LEVEL
from packaging_ai.logutil import get_logger, setup_logging

log = get_logger("api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging(LOG_LEVEL, log_file=LOG_FILE, console=True)
    repo = get_repository()
    repo.ensure_schema()
    worker = get_worker()
    worker.start()
    log.info(
        "Packaging AI API ready (version=%s, job_store=%s, api_keys=%s)",
        __version__,
        JOB_STORE,
        "configured" if API_KEYS else "MISSING",
    )
    yield
    worker.stop()


app = FastAPI(
    title="Packaging AI API",
    version=__version__,
    description="Async PSADT packaging jobs (FastAPI + SQL Server / memory store).",
    lifespan=lifespan,
)

app.include_router(jobs_router)


@app.middleware("http")
async def protect_docs(request: Request, call_next):
    """Require X-API-Key for /docs and /openapi.json (OpenAPI UI)."""
    path = request.url.path
    if path in {"/docs", "/redoc", "/openapi.json"}:
        try:
            require_api_key(request.headers.get("X-API-Key"))
        except Exception as exc:
            from fastapi import HTTPException

            if isinstance(exc, HTTPException):
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                )
            raise
    return await call_next(request)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    sql_ok: bool | None = None
    detail = None
    try:
        repo = get_repository()
        ok = repo.ping()
        if JOB_STORE == "sql":
            sql_ok = ok
            if not ok:
                detail = "SQL ping failed"
        status = "ok" if ok else "degraded"
    except Exception as exc:
        status = "degraded"
        detail = str(exc)
        if JOB_STORE == "sql":
            sql_ok = False
    return HealthResponse(
        status=status,
        version=__version__,
        job_store=JOB_STORE,
        sql_ok=sql_ok,
        detail=detail,
    )
