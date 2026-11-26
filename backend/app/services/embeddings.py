import hashlib
import math
import re
from typing import Any

try:
    import numpy as np
except ImportError:
    np = None

from app.config import settings
from app.core.logging import logger

_model_instance: Any = None
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")


def get_embedding_model():
    """Lazy load fastembed or sentence-transformers model instance."""
    global _model_instance
    if _model_instance is None:
        if settings.ENVIRONMENT == "test":
            _model_instance = ("fallback", None)
            return _model_instance

        try:
            from fastembed import TextEmbedding

            logger.info(f"Loading fastembed embedding model: {settings.EMBEDDING_MODEL_NAME}")
            _model_instance = (
                "fastembed",
                TextEmbedding(
                    model_name=settings.EMBEDDING_MODEL_NAME, cache_dir="/tmp/huggingface"
                ),
            )
            return _model_instance
        except Exception as e:
            logger.warning(f"Could not load fastembed ({e}). Trying SentenceTransformer...")

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {settings.EMBEDDING_MODEL_NAME}")
            _model_instance = (
                "sentence_transformers",
                SentenceTransformer(settings.EMBEDDING_MODEL_NAME),
            )
            return _model_instance
        except Exception as e:
            logger.warning(
                f"Could not load SentenceTransformer ({e}). Using deterministic feature-hash embedding."
            )
            _model_instance = ("fallback", None)

    return _model_instance


class EmbeddingService:
    """Embedding generation service with batching and semantic feature-hash fallback."""

    def __init__(self, dimension: int = 384, batch_size: int = 64):
        self.dimension = dimension
        self.batch_size = batch_size

    def _hash_feature(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        val = int.from_bytes(digest, "big")
        bucket = val % self.dimension
        sign = 1.0 if ((val >> 8) & 1) else -1.0
        return bucket, sign

    def _fallback_embed(self, text: str) -> list[float]:
        """Produce deterministic 384-dim signed feature-hash vector preserving lexical similarity."""
        cleaned = _INVISIBLE_RE.sub("", text or "").lower()
        tokens = re.findall(r"[a-z0-9]+", cleaned)
        if not tokens:
            vec = [0.0] * self.dimension
            vec[0] = 1.0
            return vec

        raw = [0.0] * self.dimension

        for tok in tokens:
            bucket, sign = self._hash_feature(f"w:{tok}")
            raw[bucket] += sign * 2.0
            if len(tok) > 4:
                # Prefix stem proxy handles inflections (opened/open, refunds/refund)
                b_stem, s_stem = self._hash_feature(f"s:{tok[:5]}")
                raw[b_stem] += s_stem * 1.4
            if len(tok) >= 4:
                for i in range(len(tok) - 3):
                    b_ng, s_ng = self._hash_feature(f"c:{tok[i : i + 4]}")
                    raw[b_ng] += s_ng * 0.45

        for i in range(len(tokens) - 1):
            b_bi, s_bi = self._hash_feature(f"b:{tokens[i]}_{tokens[i + 1]}")
            raw[b_bi] += s_bi * 1.25

        if np is not None:
            arr = np.array(raw, dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if norm > 0:
                arr = arr / norm
            return arr.tolist()

        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw] if norm > 0 else raw

    def embed_query(self, query: str) -> list[float]:
        """Embed a single query string."""
        backend, model = get_embedding_model()
        if backend == "fastembed":
            try:
                emb = list(model.embed([query]))[0]
                return emb.tolist() if hasattr(emb, "tolist") else list(emb)
            except Exception as e:
                logger.warning(f"Fastembed inference failed: {e}. Falling back.")
        elif backend == "sentence_transformers":
            try:
                embedding = model.encode(query, normalize_embeddings=True)
                return embedding.tolist()
            except Exception as e:
                logger.warning(f"Embedding failed on query: {e}. Using fallback.")
        return self._fallback_embed(query)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of document texts in chunks of batch_size."""
        if not texts:
            return []

        backend, model = get_embedding_model()
        if backend == "fastembed":
            try:
                embs = list(model.embed(texts))
                return [e.tolist() if hasattr(e, "tolist") else list(e) for e in embs]
            except Exception as e:
                logger.warning(f"Fastembed batch embedding failed: {e}. Falling back.")
        elif backend == "sentence_transformers":
            embeddings: list[list[float]] = []
            try:
                for i in range(0, len(texts), self.batch_size):
                    batch = texts[i : i + self.batch_size]
                    batch_embeds = model.encode(
                        batch, normalize_embeddings=True, show_progress_bar=False
                    )
                    embeddings.extend(batch_embeds.tolist())
                return embeddings
            except Exception as e:
                logger.warning(f"Batch embedding model inference failed: {e}. Falling back.")

        return [self._fallback_embed(t) for t in texts]


embedding_service = EmbeddingService(
    dimension=settings.EMBEDDING_DIMENSION,
)
