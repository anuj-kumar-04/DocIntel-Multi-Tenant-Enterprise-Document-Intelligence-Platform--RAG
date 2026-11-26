import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from app.config import settings
from app.core.logging import logger

try:
    from langfuse import Langfuse, propagate_attributes

    langfuse_host = (
        settings.LANGFUSE_HOST or settings.LANGFUSE_BASE_URL or "https://us.cloud.langfuse.com"
    )
    if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
        _langfuse_client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=langfuse_host,
        )
        logger.info(f"Langfuse client initialized successfully targeting host: {langfuse_host}")
    else:
        logger.warning("Langfuse public/secret keys not provided. Tracing is disabled.")
        _langfuse_client = None
except Exception as e:
    logger.warning(f"Langfuse client initialization skipped or failed: {e}")
    _langfuse_client = None
    propagate_attributes = None


def get_langfuse_client() -> Any | None:
    """Retrieve global Langfuse client instance."""
    return _langfuse_client


def flush_traces() -> None:
    """Synchronously flush pending Langfuse traces."""
    if _langfuse_client:
        try:
            _langfuse_client.flush()
        except Exception as e:
            logger.warning(f"Failed to flush Langfuse traces: {e}")


class TraceContext:
    """Production-grade RAG trace orchestrator with OpenTelemetry context propagation.

    Follows Langfuse best practices:
    - Strict observation typing (root span, retriever, generation).
    - Session and user attribution for multi-turn chats.
    - Tenant-level tagging and metadata isolation.
    - Token usage and cost tracking.
    - Graceful no-op fallback when unconfigured.
    """

    def __init__(
        self,
        name: str,
        user_id: str | None = None,
        session_id: str | None = None,
        org_id: str | None = None,
        tags: list[str] | None = None,
        input_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.trace_id = str(uuid.uuid4())
        self.name = name
        self.user_id = user_id
        self.session_id = session_id
        self.org_id = org_id
        self.tags = tags or []
        if org_id and f"org:{org_id}" not in self.tags:
            self.tags.append(f"org:{org_id}")
        self.input_data = input_data
        self.metadata = metadata or {}
        if org_id:
            self.metadata["org_id"] = str(org_id)
        if session_id:
            self.metadata["conversation_id"] = str(session_id)

        self._root_obs = None
        self._prop_ctx = None
        self._root_ctx = None

    @asynccontextmanager
    async def start_root(self, input_data: Any = None):
        """Context manager for the root trace observation."""
        inp = input_data if input_data is not None else self.input_data
        if _langfuse_client and propagate_attributes:
            try:
                self._prop_ctx = propagate_attributes(
                    user_id=self.user_id,
                    session_id=self.session_id,
                    tags=self.tags,
                    metadata=self.metadata,
                )
                self._prop_ctx.__enter__()

                self._root_ctx = _langfuse_client.start_as_current_observation(
                    name=self.name,
                    as_type="span",
                    input=inp,
                    metadata=self.metadata,
                )
                self._root_obs = self._root_ctx.__enter__()
            except Exception as e:
                logger.warning(f"Error starting Langfuse root trace: {e}")
                self._root_obs = None

        try:
            yield self
        finally:
            if self._root_ctx:
                try:
                    self._root_ctx.__exit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Error closing Langfuse root observation: {e}")
            if self._prop_ctx:
                try:
                    self._prop_ctx.__exit__(None, None, None)
                except Exception as e:
                    logger.debug(f"Error closing Langfuse propagate_attributes: {e}")

            # Flush in background thread to avoid blocking response stream
            if _langfuse_client:
                try:
                    await asyncio.to_thread(_langfuse_client.flush)
                except Exception:
                    pass

    def set_output(self, output: Any) -> None:
        """Update output on root observation."""
        if self._root_obs:
            try:
                self._root_obs.update(output=output)
            except Exception as e:
                logger.debug(f"Failed to update root observation output: {e}")

    @asynccontextmanager
    async def retriever_step(self, name: str = "hybrid_retrieval", input_data: Any = None):
        """Context manager tracing a retrieval step with observation type 'retriever'."""
        obs = None
        ctx = None
        if _langfuse_client:
            try:
                ctx = _langfuse_client.start_as_current_observation(
                    name=name,
                    as_type="retriever",
                    input=input_data,
                )
                obs = ctx.__enter__()
            except Exception as e:
                logger.debug(f"Failed to start retriever observation: {e}")
        try:
            yield obs
        finally:
            if ctx:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    @asynccontextmanager
    async def cache_step(self, name: str = "semantic_cache_lookup", input_data: Any = None):
        """Context manager tracing a cache lookup step."""
        obs = None
        ctx = None
        if _langfuse_client:
            try:
                ctx = _langfuse_client.start_as_current_observation(
                    name=name,
                    as_type="span",
                    input=input_data,
                )
                obs = ctx.__enter__()
            except Exception as e:
                logger.debug(f"Failed to start cache observation: {e}")
        try:
            yield obs
        finally:
            if ctx:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    @asynccontextmanager
    async def span(self, name: str, metadata: dict[str, Any] | None = None, input_data: Any = None):
        """Generic nested span observation."""
        obs = None
        ctx = None
        if _langfuse_client:
            try:
                ctx = _langfuse_client.start_as_current_observation(
                    name=name,
                    as_type="span",
                    input=input_data,
                    metadata=metadata,
                )
                obs = ctx.__enter__()
            except Exception as e:
                logger.debug(f"Failed to start span {name}: {e}")
        try:
            yield obs
        finally:
            if ctx:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass

    def log_generation(
        self,
        name: str = "llm_generation",
        model: str = "unknown",
        input_messages: Any = None,
        output: str = "",
        usage: dict[str, int] | None = None,
        cost: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an LLM generation observation with token usage and cost metrics."""
        if not _langfuse_client:
            return

        try:
            usage_details = None
            if usage:
                usage_details = {
                    "input": usage.get("prompt_tokens", usage.get("input", 0)),
                    "output": usage.get("completion_tokens", usage.get("output", 0)),
                    "total": usage.get("total_tokens", usage.get("total", 0)),
                }

            cost_details = {"total": cost} if cost is not None else None

            with _langfuse_client.start_as_current_observation(
                name=name,
                as_type="generation",
                model=model,
                input=input_messages,
                metadata=metadata,
            ) as gen_obs:
                gen_obs.update(
                    output=output,
                    usage_details=usage_details,
                    cost_details=cost_details,
                )
        except Exception as e:
            logger.warning(f"Failed to record Langfuse generation observation: {e}")
