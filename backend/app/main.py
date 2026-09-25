from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.v1.router import api_v1_router
from app.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestContextMiddleware, logger
from app.core.rate_limit import limiter
from app.deps import engine
from app.models.base import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan managing startup and teardown lifecycle."""
    logger.info(f"Starting {settings.APP_NAME} in [{settings.ENVIRONMENT}] mode")

    # In development or test, automatically verify schema tables
    if settings.ENVIRONMENT in ["development", "test"]:
        try:
            async with engine.begin() as conn:
                # Ensure pgvector extension if PostgreSQL
                if "postgresql" in settings.DATABASE_URL:
                    try:
                        from sqlalchemy import text
                        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    except Exception as e:
                        logger.warning(f"Vector extension notice: {e}")
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema initialized successfully")
        except Exception as e:
            logger.warning(f"Database schema auto-creation notice: {e}")

    yield

    logger.info(f"Shutting down {settings.APP_NAME} cleanly")
    await engine.dispose()


def create_application() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="Multi-Tenant Enterprise Document Intelligence Platform with Hybrid Retrieval, Citations & Cost Controls",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Attach rate limiter state
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # 1. Custom Exception Handlers
    register_exception_handlers(app)

    # 2. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            settings.FRONTEND_URL,
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Correlation Request-ID & Structured Logging Middleware
    app.add_middleware(RequestContextMiddleware)

    # 4. Prometheus Metrics Instrumentor
    if settings.PROMETHEUS_METRICS_ENABLED:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")

    # 5. Include API v1 Router
    app.include_router(api_v1_router)

    # 6. Mount public directory for zero-dependency standalone dashboard
    public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "public"))
    if os.path.exists(public_dir):
        app.mount("/app", StaticFiles(directory=public_dir, html=True), name="static_app")

    @app.get("/", tags=["Root"])
    async def root():
        return {
            "platform": settings.APP_NAME,
            "version": "1.0.0",
            "status": "operational",
            "documentation": "/docs",
            "api_v1": "/api/v1",
            "executive_ui": "/app/index.html",
        }

    return app


app = create_application()
