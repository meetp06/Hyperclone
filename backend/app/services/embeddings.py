"""EmbeddingProvider interface + fastembed default impl.

Keep all consumers (memory service, chat) behind the abstract base so we
can swap to OpenAI / Cohere / local-llama embeddings without touching them.

SCALE: embedding is currently synchronous on the request thread. In
production, push to a queue worker (Redis stream → worker → upsert) so
ingestion latency does not block the API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from threading import Lock

from app.config import get_settings


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        """Return one vector per input string, in order."""


class FastEmbedProvider(EmbeddingProvider):
    """Local fastembed (ONNX) — no API key, ~30MB BGE-small download on first use."""

    _model = None
    _lock = Lock()

    def __init__(self, model_name: str | None = None, dim: int | None = None) -> None:
        settings = get_settings()
        self._model_name = model_name or settings.embedding_model
        self._dim = dim or settings.embedding_dim

    @property
    def dim(self) -> int:
        return self._dim

    def _ensure_model(self):  # type: ignore[no-untyped-def]
        if FastEmbedProvider._model is None:
            with FastEmbedProvider._lock:
                if FastEmbedProvider._model is None:
                    from fastembed import TextEmbedding

                    FastEmbedProvider._model = TextEmbedding(model_name=self._model_name)
        return FastEmbedProvider._model

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        model = self._ensure_model()
        # fastembed returns numpy arrays; convert to plain lists for Qdrant client.
        return [vec.tolist() for vec in model.embed(list(texts))]


_default: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    global _default
    if _default is None:
        _default = FastEmbedProvider()
    return _default
