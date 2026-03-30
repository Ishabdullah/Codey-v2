"""
nomic-embed-text client — calls the existing Codey-v2 embed server on port 8082.

Reuses the same llama-server instance that core/embeddings.py uses for RAG,
so no additional processes are needed.
"""

import json
import urllib.request
import urllib.error
from typing import List, Optional


class NomicEmbedClient:
    """
    HTTP client for the nomic-embed-text llama-server on port 8082.

    Args:
        host: Server host (default localhost)
        port: Server port (default 8082, from config)
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8082):
        self.base_url = f"http://{host}:{port}"
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if the embed server is reachable."""
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request(
                f"{self.base_url}/health",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=2):
                self._available = True
        except Exception:
            self._available = False
        return self._available

    def embed(self, text: str) -> Optional[List[float]]:
        """
        Embed a single text string.

        Returns:
            List of floats (768-dim for nomic-embed-text-v1.5), or None on error.
        """
        results = self.embed_batch([text])
        return results[0] if results else None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Embed a batch of texts.

        Returns:
            List of embedding vectors (same order as input).
            Failed embeddings are None.
        """
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)

        payload = json.dumps({"content": texts}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # llama-server returns {"data": [{"embedding": [...], "index": N}, ...]}
            for item in data.get("data", []):
                idx = item.get("index", 0)
                vec = item.get("embedding", [])
                if idx < len(results):
                    results[idx] = vec

        except urllib.error.URLError:
            self._available = False
        except Exception:
            pass

        return results
