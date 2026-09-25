import json
from typing import Any
import numpy as np
import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import logger
from app.services.embeddings import embedding_service


class SemanticCache:
    """Redis-backed tenant-isolated semantic cache using embedding cosine similarity."""

    def __init__(self, threshold: float = 0.97):
        self.threshold = threshold
        self._redis: aioredis.Redis | None = None
        self.hits = 0
        self.misses = 0

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def get(self, org_id: str, query: str) -> dict[str, Any] | None:
        """Look up answer in semantic cache for the tenant organization."""
        if not settings.SEMANTIC_CACHE_ENABLED:
            return None

        try:
            r = await self._get_redis()
            cache_key = f"org:{org_id}:semantic_cache"
            entries = await r.hgetall(cache_key)

            if not entries:
                self.misses += 1
                return None

            query_vec = embedding_service.embed_query(query)
            best_score = -1.0
            best_payload = None

            for _, val_json in entries.items():
                entry = json.loads(val_json)
                sim = self._cosine_similarity(query_vec, entry["embedding"])
                if sim > best_score:
                    best_score = sim
                    best_payload = entry

            if best_score >= self.threshold and best_payload is not None:
                self.hits += 1
                logger.info(
                    f"Semantic cache HIT for org {org_id} (similarity: {best_score:.4f})"
                )
                return {
                    "answer": best_payload["answer"],
                    "citations": best_payload.get("citations", []),
                    "cached": True,
                    "similarity": best_score,
                }

            self.misses += 1
            return None

        except Exception as e:
            logger.warning(f"Semantic cache lookup skipped: {e}")
            self.misses += 1
            return None

    async def set(
        self,
        org_id: str,
        query: str,
        answer: str,
        citations: list[dict[str, Any]],
    ) -> None:
        """Store query, embedding, and generated answer in cache."""
        if not settings.SEMANTIC_CACHE_ENABLED:
            return

        try:
            r = await self._get_redis()
            cache_key = f"org:{org_id}:semantic_cache"
            query_vec = embedding_service.embed_query(query)

            entry_data = {
                "query": query,
                "embedding": query_vec,
                "answer": answer,
                "citations": citations,
            }
            # Limit cache size per org to 200 items to conserve memory
            cache_len = await r.hlen(cache_key)
            if cache_len > 200:
                keys = await r.hkeys(cache_key)
                if keys:
                    await r.hdel(cache_key, keys[0])

            # Use short query hash as field
            field = str(hash(query))
            await r.hset(cache_key, field, json.dumps(entry_data))
            # Expire cache key in 7 days
            await r.expire(cache_key, 7 * 86400)
        except Exception as e:
            logger.warning(f"Failed to write to semantic cache: {e}")

    def get_hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total > 0 else 0.0


semantic_cache = SemanticCache(threshold=settings.SEMANTIC_CACHE_THRESHOLD)
