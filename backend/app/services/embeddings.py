import hashlib
import math
from typing import Any

try:
    import numpy as np
except ImportError:
    np = None

from app.config import settings
from app.core.logging import logger

_model_instance: Any = None


def get_embedding_model():
    """Lazy load fastembed or sentence-transformers model instance."""
    global _model_instance
    if _model_instance is None:
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
                f"Could not load SentenceTransformer ({e}). Using deterministic embedding fallback."
            )
            _model_instance = ("fallback", None)

    return _model_instance


class EmbeddingService:
    """Embedding generation service with batching and fallbacks."""

    def __init__(self, dimension: int = 384, batch_size: int = 64):
        self.dimension = dimension
        self.batch_size = batch_size

    def _fallback_embed(self, text: str) -> list[float]:
        """Produce deterministic 384-dim normalized vector from text content."""
        h = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(h[:4], "big")

        if np is not None:
            rng = np.random.RandomState(seed)
            vec = rng.randn(self.dimension).astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return vec.tolist()
        else:
            import random

            rng = random.Random(seed)
            raw = [rng.gauss(0, 1) for _ in range(self.dimension)]
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

        # Fallback path
        return [self._fallback_embed(t) for t in texts]


embedding_service = EmbeddingService(
    dimension=settings.EMBEDDING_DIMENSION,
)
