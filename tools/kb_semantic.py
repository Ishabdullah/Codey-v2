"""
Knowledge Base Search — Phase 1 (v2.6.1)

Search backends in priority order:
  1. fastembed          — ONNX Runtime (no torch). Desktop/server only.
  2. sentence-transformers — PyTorch. Desktop/server only.
  3. BM25 (built-in)   — Pure Python, zero dependencies, always active.
                          This is the primary mode on Termux/Android ARM64
                          where neither onnxruntime nor torch have wheels.

BM25 (Okapi BM25) is a proven ranking algorithm used by Elasticsearch,
Lucene, and most production search engines. It substantially outperforms
simple word overlap for retrieval relevance.

No install needed for Termux — BM25 is always active.
Optional semantic upgrade (desktop/server only):
    pip install fastembed              # ONNX, no torch
    pip install sentence-transformers  # torch required

Usage:
    from tools.kb_semantic import semantic_search, keyword_fallback, build_semantic_index

    results = semantic_search("Flask error handling", top_k=4)  # auto-selects backend
    results = keyword_fallback("Flask error handling", top_k=4) # BM25, always works
"""

import json
import math
from collections import Counter
from pathlib import Path

from tools.kb_scraper import KB_ROOT

# ── Optional embedding backends (desktop/server only) ────────────────────────
HAS_FASTEMBED = False
HAS_SENTENCE_TRANSFORMERS = False
np = None

try:
    import numpy as np
    _np_ok = True
except ImportError:
    _np_ok = False

if _np_ok:
    try:
        from fastembed import TextEmbedding as _FETextEmbedding
        HAS_FASTEMBED = True
    except ImportError:
        pass

    if not HAS_FASTEMBED:
        try:
            from sentence_transformers import SentenceTransformer as _STModel
            HAS_SENTENCE_TRANSFORMERS = True
        except ImportError:
            pass

HAS_SEMANTIC = HAS_FASTEMBED or HAS_SENTENCE_TRANSFORMERS

EMBED_MODEL_FASTEMBED = "BAAI/bge-small-en-v1.5"
EMBED_MODEL_ST        = "all-MiniLM-L6-v2"

_model = None


def _get_model():
    global _model
    if _model is not None:
        return _model
    if HAS_FASTEMBED:
        _model = _FETextEmbedding(EMBED_MODEL_FASTEMBED)
    elif HAS_SENTENCE_TRANSFORMERS:
        _model = _STModel(EMBED_MODEL_ST)
    else:
        raise ImportError("No embedding backend available.")
    return _model


def _encode(texts: list) -> "np.ndarray":
    model = _get_model()
    if HAS_FASTEMBED:
        return np.array(list(model.embed(texts)), dtype="float32")
    return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)


# ── BM25 helpers (pure Python) ────────────────────────────────────────────────

def _tokenize(text: str) -> list:
    """Lowercase word tokens, min length 2, strip punctuation."""
    import re
    return re.findall(r"[a-z0-9_]{2,}", text.lower())


class _BM25Index:
    """
    In-memory BM25 (Okapi BM25) index over a list of chunk dicts.

    k1=1.5, b=0.75 are standard defaults used by Elasticsearch/Lucene.
    IDF is computed per-corpus at build time for accurate scoring.
    """
    K1 = 1.5
    B  = 0.75

    def __init__(self, chunks: list):
        self.chunks = chunks
        self.n = len(chunks)
        if self.n == 0:
            self.avg_dl = 0
            self.idf = {}
            self.doc_tokens = []
            return

        self.doc_tokens = [_tokenize(c.get("text", "")) for c in chunks]
        doc_lens = [len(t) for t in self.doc_tokens]
        self.avg_dl = sum(doc_lens) / max(self.n, 1)

        # IDF: log((N - df + 0.5) / (df + 0.5) + 1) — Robertson IDF
        df: dict = {}
        for tokens in self.doc_tokens:
            for w in set(tokens):
                df[w] = df.get(w, 0) + 1
        self.idf = {
            w: math.log((self.n - f + 0.5) / (f + 0.5) + 1.0)
            for w, f in df.items()
        }

    def score(self, query_tokens: list, doc_idx: int) -> float:
        tokens = self.doc_tokens[doc_idx]
        dl = len(tokens)
        tf_map = Counter(tokens)
        s = 0.0
        for w in query_tokens:
            if w not in self.idf:
                continue
            tf = tf_map.get(w, 0)
            numerator = tf * (self.K1 + 1)
            denominator = tf + self.K1 * (1 - self.B + self.B * dl / max(self.avg_dl, 1))
            s += self.idf[w] * numerator / max(denominator, 1e-8)
        return s

    def search(self, query: str, top_k: int = 5) -> list:
        """Return top_k results as {text, source, score} dicts."""
        if self.n == 0:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        scores = [(self.score(q_tokens, i), i) for i in range(self.n)]
        scores.sort(reverse=True)

        results = []
        for score, idx in scores[:top_k]:
            if score <= 0:
                break
            c = self.chunks[idx]
            results.append({
                "text":   c.get("text", ""),
                "source": c.get("source", c.get("filename", "")),
                "score":  score,
            })
        return results


def _load_all_chunks() -> list:
    """Load all chunks from knowledge/embeddings/*.chunks.json."""
    chunk_dir = KB_ROOT / "embeddings"
    if not chunk_dir.exists():
        return []
    all_chunks = []
    for cf in sorted(chunk_dir.glob("*.chunks.json")):
        try:
            with open(cf, encoding="utf-8") as f:
                all_chunks.extend(json.load(f))
        except Exception:
            pass
    return all_chunks


# ── Semantic index build / load ───────────────────────────────────────────────

def build_semantic_index() -> int:
    """
    Build a vector index for semantic search (optional upgrade).

    Not needed for BM25 — call this only if you have fastembed or
    sentence-transformers installed.

    Returns number of embeddings built, or 0 if no backend available.
    """
    if not HAS_SEMANTIC:
        print("[kb_semantic] No vector embedding backend installed.")
        print("  BM25 keyword search is active — no install needed on Termux.")
        print("  Optional semantic upgrade (desktop/server):")
        print("    pip install fastembed            # no torch, ONNX-based")
        print("    pip install sentence-transformers # requires torch")
        return 0

    all_chunks = _load_all_chunks()
    if not all_chunks:
        print("[kb_semantic] No chunks found. Run index_directory() first.")
        return 0

    texts = [c["text"] for c in all_chunks]
    backend = "fastembed" if HAS_FASTEMBED else "sentence-transformers"
    print(f"[kb_semantic] Computing {len(texts)} embeddings via {backend}...")

    try:
        embeddings = _encode(texts)
    except Exception as e:
        print(f"[kb_semantic] Embedding failed: {e}")
        return 0

    chunk_dir = KB_ROOT / "embeddings"
    np.save(str(chunk_dir / "vectors.npy"), embeddings.astype("float32"))

    mapping = [
        {
            "id":       c["id"],
            "source":   c.get("source", ""),
            "category": c.get("category", ""),
            "filename": c.get("filename", ""),
            "text":     c["text"],
        }
        for c in all_chunks
    ]
    with open(chunk_dir / "mapping.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f)

    print(f"[kb_semantic] Saved {len(embeddings)} embeddings → vectors.npy")
    return len(embeddings)


def _load_vector_index() -> tuple:
    """Load pre-built vector index. Returns (vectors, mapping) or (None, None)."""
    chunk_dir = KB_ROOT / "embeddings"
    vp = chunk_dir / "vectors.npy"
    mp = chunk_dir / "mapping.json"
    if not vp.exists() or not mp.exists():
        return None, None
    try:
        vectors = np.load(str(vp))
        with open(mp, encoding="utf-8") as f:
            mapping = json.load(f)
        return vectors, mapping
    except Exception:
        return None, None


# ── Public search API ─────────────────────────────────────────────────────────

def semantic_search(query: str, top_k: int = 5) -> list:
    """
    Search the knowledge base. Auto-selects the best available backend:
      vector index (fastembed/sentence-transformers) → BM25 (always available).

    Args:
        query: Search query
        top_k: Number of results

    Returns:
        List of {text, source, score} dicts, best match first.
    """
    # Try vector search if backend + index available
    if HAS_SEMANTIC and np is not None:
        vectors, mapping = _load_vector_index()
        if vectors is not None and mapping:
            try:
                q_vec = _encode([query])
                norms = np.linalg.norm(vectors, axis=1)
                q_norm = np.linalg.norm(q_vec)
                if q_norm > 1e-8:
                    sims = np.dot(vectors, q_vec.T).flatten() / (norms * q_norm + 1e-8)
                    top_idx = np.argsort(sims)[-top_k:][::-1]
                    results = []
                    for i in top_idx:
                        if i < len(mapping):
                            meta = mapping[int(i)]
                            results.append({
                                "text":   meta["text"],
                                "source": meta.get("source", meta.get("filename", "")),
                                "score":  float(sims[i]),
                            })
                    if results:
                        return results
            except Exception:
                pass

    # BM25 fallback — always works
    return keyword_fallback(query, top_k)


def keyword_fallback(query: str, top_k: int = 5) -> list:
    """
    BM25 search over all indexed chunks. Zero dependencies, always active.

    Uses Okapi BM25 (k1=1.5, b=0.75) — the same algorithm as Elasticsearch.
    Substantially better than simple word overlap for multi-word queries.

    Args:
        query: Search query
        top_k: Number of results

    Returns:
        List of {text, source, score} dicts, best match first.
    """
    all_chunks = _load_all_chunks()
    if not all_chunks:
        return []
    index = _BM25Index(all_chunks)
    return index.search(query, top_k=top_k)


def has_index() -> bool:
    """Return True if the KB has any indexed chunks."""
    chunk_dir = KB_ROOT / "embeddings"
    if not chunk_dir.exists():
        return False
    return any(chunk_dir.glob("*.chunks.json"))


def index_stats() -> dict:
    """Return stats about the current index."""
    chunk_dir = KB_ROOT / "embeddings"
    if not chunk_dir.exists():
        return {"chunk_files": 0, "total_chunks": 0, "has_semantic": False, "backend": "none"}

    chunk_files = list(chunk_dir.glob("*.chunks.json"))
    total = 0
    for cf in chunk_files:
        try:
            with open(cf) as f:
                total += len(json.load(f))
        except Exception:
            pass

    if HAS_FASTEMBED:
        backend = "fastembed+BM25"
    elif HAS_SENTENCE_TRANSFORMERS:
        backend = "sentence-transformers+BM25"
    else:
        backend = "BM25 (keyword, no install needed)"

    return {
        "chunk_files":  len(chunk_files),
        "total_chunks": total,
        "has_semantic": (chunk_dir / "vectors.npy").exists(),
        "backend":      backend,
        "kb_root":      str(KB_ROOT),
    }
