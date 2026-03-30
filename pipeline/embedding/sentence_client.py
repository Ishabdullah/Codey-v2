"""
sentence-transformers fallback embedder.

Used when the nomic embed server (port 8082) is offline.
Lazy-loads all-MiniLM-L6-v2 (384-dim, ~80MB) on first call.
"""

from typing import List, Optional


class SentenceEmbedClient:
    """
    Local sentence-transformers embedder.

    Args:
        model_name: HF model id (default all-MiniLM-L6-v2)
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._dim: Optional[int] = None

    def _load(self) -> bool:
        if self._model is not None:
            return True
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self._dim   = self._model.get_sentence_embedding_dimension()
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def is_available(self) -> bool:
        return self._load()

    @property
    def dim(self) -> int:
        return self._dim or 384

    def embed(self, text: str) -> Optional[List[float]]:
        results = self.embed_batch([text])
        return results[0] if results else None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        if not texts:
            return []
        if not self._load():
            return [None] * len(texts)
        try:
            vecs = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            return [v.tolist() for v in vecs]
        except Exception:
            return [None] * len(texts)
