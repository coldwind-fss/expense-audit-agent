import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .api_agents import router as agents_router
from .api_claims import router as claims_router
from .api_materials import router as materials_router
from .api_operations import router as operations_router
from .api_submissions import router as submissions_router
from .config import settings
from .db import engine
from .errors import AppError
from .observability import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="智能报销工作台", version="0.1.0")
app.include_router(claims_router)
app.include_router(materials_router)
app.include_router(agents_router)
app.include_router(submissions_router)
app.include_router(operations_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Action-Reason"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = uuid4().hex
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info(
        "http.completed",
        extra={
            "request_id": request.state.request_id,
            "workspace_id": getattr(request.state, "workspace_id", None),
            "status": response.status_code,
            "elapsed_ms": round((perf_counter() - started) * 1000),
        },
    )
    return response


@app.exception_handler(AppError)
async def application_error(request: Request, error: AppError):
    return JSONResponse(
        status_code=error.status,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "request_id": request.state.request_id,
                "retryable": False,
                "details": error.details,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, error: RequestValidationError):
    details = [{"path": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in error.errors()]
    return await application_error(request, AppError("VALIDATION_ERROR", "请核对输入字段", 422, details))


@app.get("/api/v1/health/live")
def live() -> dict:
    return {"service": "reimbursement", "version": "0.1.0", "status": "alive"}


@app.get("/api/v1/health/ready")
def ready() -> dict:
    try:
        with engine.connect() as connection:
            schema_version = connection.execute(
                text("SELECT version_num FROM app.alembic_version LIMIT 1")
            ).scalar_one()
            connection.execute(text("SELECT 1 FROM app.claims LIMIT 0"))
            connection.execute(text("SELECT 1 FROM agent_runtime.checkpoints LIMIT 0"))
    except SQLAlchemyError as error:
        raise AppError("SERVICE_UNAVAILABLE", "数据库或迁移尚未就绪", 503) from error
    return {
        "status": "ready",
        "schema_version": schema_version,
        "model_mode": settings().model_mode,
        "enterprise_mode": "stub",
    }
