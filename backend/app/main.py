import os
from contextlib import asynccontextmanager

import app.models  # noqa: F401  Ensure all ORM tables (incl. audit_logs) register with Base.metadata
from app.api.v1.router import api_v1_router
from app.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestContextMiddleware, logger
from app.core.rate_limit import limiter
from app.core.tracing import flush_traces
from app.deps import engine
from app.models.base import Base
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardened HTTP security response headers on all API responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        if settings.ENVIRONMENT == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
            )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing startup and teardown lifecycle."""
    logger.info(f"Starting {settings.APP_NAME} in [{settings.ENVIRONMENT}] mode")

    # Verify/create schema tables cleanly (safe idempotent startup for dev, test, or first-boot prod)
    if settings.ENVIRONMENT in ["development", "test", "production"]:
        try:
            async with engine.begin() as conn:
                if "postgresql" in settings.DATABASE_URL:
                    try:
                        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    except Exception as e:
                        logger.warning(f"Vector extension notice: {e}")
                await conn.run_sync(Base.metadata.create_all)
                if "postgresql" in settings.DATABASE_URL:
                    await conn.execute(
                        text(
                            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS document_ids JSONB;"
                        )
                    )
            logger.info("Database schema initialized successfully")
        except Exception as e:
            logger.warning(f"Database schema auto-creation notice: {e}")

    yield

    logger.info(f"Shutting down {settings.APP_NAME} cleanly")
    flush_traces()
    await engine.dispose()


def create_application() -> FastAPI:
    """FastAPI application factory with hardened production defaults."""
    is_prod = settings.ENVIRONMENT == "production"
    expose_docs = (not is_prod) or settings.ENABLE_SWAGGER_IN_PROD

    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="Multi-Tenant Enterprise Document Intelligence Platform with Hybrid Retrieval, Citations & Cost Controls",
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
        lifespan=lifespan,
    )

    # Attach rate limiter state & middleware
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # 1. Custom Exception Handlers
    register_exception_handlers(app)

    # 2. CORS Middleware (strict single-origin in production)
    allowed_origins = (
        [settings.FRONTEND_URL]
        if is_prod
        else [
            settings.FRONTEND_URL,
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # 3. Security Response Headers & Structured Correlation Middleware
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    # 4. Prometheus Metrics Instrumentor
    if settings.PROMETHEUS_METRICS_ENABLED:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    # 5. Include API v1 Router
    app.include_router(api_v1_router)

    # 6. Mount public directory for zero-dependency standalone dashboard (non-production)
    if not is_prod:
        static_candidates = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static")),
            os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "public")
            ),
            "/app/static",
        ]
        for candidate in static_candidates:
            if os.path.exists(candidate) and os.path.isdir(candidate):
                app.mount("/app", StaticFiles(directory=candidate, html=True), name="static_app")
                break

    @app.get("/", tags=["Root"])
    async def root():
        payload = {
            "platform": settings.APP_NAME,
            "version": "1.0.0",
            "status": "operational",
            "api_v1": "/api/v1",
        }
        if expose_docs:
            payload["documentation"] = "/docs"
        return payload

    return app


app = create_application()
