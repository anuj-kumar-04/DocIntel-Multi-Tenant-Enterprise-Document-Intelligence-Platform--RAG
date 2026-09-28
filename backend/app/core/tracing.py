import uuid
from contextlib import asynccontextmanager
from typing import Any

from app.config import settings
from app.core.logging import logger

try:
    from langfuse import Langfuse

    _langfuse_client = Langfuse(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
    )
except Exception as e:
    logger.warning(f"Langfuse client disabled or unreachable: {e}")
    _langfuse_client = None


class TraceContext:
    """Wrapper managing trace and span lifecycle for retrieval and generation."""

    def __init__(self, name: str, user_id: str | None = None, org_id: str | None = None):
        self.trace_id = str(uuid.uuid4())
        self.name = name
        self.user_id = user_id
        self.org_id = org_id
        self._trace = None

        if _langfuse_client:
            try:
                self._trace = _langfuse_client.trace(
                    id=self.trace_id,
                    name=name,
                    user_id=user_id,
                    metadata={"org_id": org_id},
                )
            except Exception as e:
                logger.warning(f"Failed to create Langfuse trace: {e}")

    @asynccontextmanager
    async def span(self, name: str, metadata: dict[str, Any] | None = None):
        span_obj = None
        if self._trace:
            try:
                span_obj = self._trace.span(name=name, metadata=metadata or {})
            except Exception as e:
                logger.warning(f"Failed to create Langfuse span {name}: {e}")
        try:
            yield span_obj
        finally:
            if span_obj:
                try:
                    span_obj.end()
                except Exception:
                    pass

    def log_generation(
        self,
        name: str,
        model: str,
        input_messages: Any,
        output: str,
        usage: dict[str, int] | None = None,
        cost: float | None = None,
    ):
        if self._trace:
            try:
                self._trace.generation(
                    name=name,
                    model=model,
                    input=input_messages,
                    output=output,
                    usage=usage,
                    cost=cost,
                )
            except Exception as e:
                logger.warning(f"Failed to log Langfuse generation: {e}")
