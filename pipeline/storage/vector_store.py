"""
Vector store — wraps hnswlib for ARM/Android compatible ANN search.

Falls back to a pure-numpy brute-force store if hnswlib is not installed.

The store assigns sequential integer IDs to vectors (matching the SQLite
records table). IDs are stable across save/load cycles.
"""

import json
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple


class VectorStore:
    """
    ANN vector index backed by hnswlib (or numpy fallback).

    Args:
        dim:        Embedding dimension (768 for nomic, 384 for MiniLM)
        index_path: Path to save/load the index (.bin file)
        max_elements: Pre-allocated capacity (grows automatically)
        use_cosine:   Use cosine similarity (default True)
    """

    def __init__(
        self,
        dim: int,
        index_path: str,
        max_elements: int = 500_000,
        use_cosine: bool = True,
    ):
        self.dim          = dim
        self.index_path   = Path(index_path)
        self.max_elements = max_elements
        self.space        = "cosine" if use_cosine else "l2"
        self._index       = None
        self._next_id     = 0
        self._use_hnswlib = False

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_or_create()

    # ── Init ──────────────────────────────────────────────────────────────────

    def _load_or_create(self) -> None:
        try:
            import hnswlib
            self._use_hnswlib = True
            index = hnswlib.Index(space=self.space, dim=self.dim)
            bin_path = self._bin_path()
            meta_path = self._meta_path()

            if bin_path.exists() and meta_path.exists():
                index.load_index(str(bin_path), max_elements=self.max_elements)
                with open(meta_path) as f:
                    meta = json.load(f)
                self._next_id = meta.get("next_id", index.get_current_count())
            else:
                index.init_index(
                    max_elements=self.max_elements,
                    ef_construction=200,
                    M=16,
                )
                index.set_ef(50)

            self._index = index

        except ImportError:
            # Numpy fallback — brute-force cosine search
            self._use_hnswlib = False
            npz_path = self._npz_path()
            if npz_path.exists():
                data = np.load(str(npz_path), allow_pickle=False)
                self._np_vecs = data["vecs"]
                self._next_id = int(data["next_id"])
            else:
                self._np_vecs = np.empty((0, self.dim), dtype=np.float32)

    # ── Insert ────────────────────────────────────────────────────────────────

    def add(self, vector: List[float]) -> int:
        """
        Add a single vector. Returns its assigned integer ID.
        """
        vec_id = self._next_id
        arr    = np.array(vector, dtype=np.float32)

        if self._use_hnswlib:
            self._index.add_items(arr.reshape(1, -1), [vec_id])
        else:
            self._np_vecs = np.vstack([self._np_vecs, arr.reshape(1, -1)]) if len(self._np_vecs) else arr.reshape(1, -1)

        self._next_id += 1
        return vec_id

    def add_batch(self, vectors: List[List[float]]) -> List[int]:
        """
        Add multiple vectors. Returns list of assigned IDs.
        """
        if not vectors:
            return []

        start_id = self._next_id
        ids      = list(range(start_id, start_id + len(vectors)))
        arr      = np.array(vectors, dtype=np.float32)

        if self._use_hnswlib:
            self._index.add_items(arr, ids)
        else:
            if len(self._np_vecs):
                self._np_vecs = np.vstack([self._np_vecs, arr])
            else:
                self._np_vecs = arr

        self._next_id += len(vectors)
        return ids

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
    ) -> List[Tuple[int, float]]:
        """
        Find the top_k most similar vectors.

        Returns:
            List of (vector_id, distance) tuples, sorted by distance ascending.
            For cosine space, distance = 1 - cosine_similarity.
        """
        if self._next_id == 0:
            return []

        query = np.array(query_vector, dtype=np.float32)

        if self._use_hnswlib:
            k = min(top_k, self._next_id)
            labels, distances = self._index.knn_query(query.reshape(1, -1), k=k)
            return list(zip(labels[0].tolist(), distances[0].tolist()))

        else:
            # Brute-force cosine similarity
            norms  = np.linalg.norm(self._np_vecs, axis=1, keepdims=True)
            normed = self._np_vecs / (norms + 1e-10)
            qnorm  = query / (np.linalg.norm(query) + 1e-10)
            sims   = normed @ qnorm
            k      = min(top_k, len(sims))
            top_idx = np.argpartition(-sims, k - 1)[:k]
            top_idx = top_idx[np.argsort(-sims[top_idx])]
            return [(int(i), float(1.0 - sims[i])) for i in top_idx]

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self) -> None:
        """Persist the index to disk."""
        if self._use_hnswlib:
            self._index.save_index(str(self._bin_path()))
            with open(self._meta_path(), "w") as f:
                json.dump({"next_id": self._next_id, "dim": self.dim, "space": self.space}, f)
        else:
            np.savez_compressed(
                str(self._npz_path()),
                vecs=self._np_vecs,
                next_id=np.array(self._next_id),
            )

    def count(self) -> int:
        return self._next_id

    # ── Path helpers ──────────────────────────────────────────────────────────

    def _bin_path(self) -> Path:
        return self.index_path.with_suffix(".bin")

    def _meta_path(self) -> Path:
        return self.index_path.with_suffix(".meta.json")

    def _npz_path(self) -> Path:
        return self.index_path.with_suffix(".npz")
