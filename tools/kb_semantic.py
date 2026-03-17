"""
Knowledge Base Search — hybrid retrieval upgrade

Search strategy (auto-selected at runtime):

  HYBRID (best quality — used when vector index exists + llama-server running)
    BM25 top-20  ─┐
                   ├─ RRF merge ─→ top-k results
    Vector top-20 ─┘

  BM25-ONLY (always active, zero dependencies)
    Okapi BM25 (k1=1.5, b=0.75) — same as Elasticsearch/Lucene.
    Primary mode on Termux/Android ARM64.

Embedding backends for building the vector index (priority order):
  1. llama-server /v1/embeddings  — already running, zero new deps, works on Termux
  2. fastembed                    — ONNX, no torch, desktop/server only
  3. sentence-transformers        — torch required, desktop/server only

RRF (Reciprocal Rank Fusion):
  score = Σ 1/(rank + 60) across result lists.
  No score normalization needed. Proven +15-25% recall over single-method search.

Query embeddings are cached (LRU, 20 entries) to avoid re-embedding repeated queries.

Usage:
    # One-time index build (via setup_skills.sh, or manually):
    from tools.kb_semantic import build_semantic_index
    n = build_semantic_index()   # uses best available backend

    # Search (auto-selects hybrid or BM25):
    from tools.kb_semantic import semantic_search
    results = semantic_search("Flask error handling", top_k=4)

    # Force BM25 only:
    from tools.kb_semantic import keyword_fallback
    results = keyword_fallback("Flask error handling", top_k=4)

    # Check status:
    from tools.kb_semantic import check_llama_embeddings, index_stats
    print(check_llama_embeddings())  # True/False
    print(index_stats())
"""

import json
import math
import os
from collections import Counter, OrderedDict
from pathlib import Path

from tools.kb_scraper import KB_ROOT

# ── numpy ─────────────────────────────────────────────────────────────────────
try:
    import numpy as np
    _np_ok = True
except ImportError:
    np = None
    _np_ok = False

# ── Legacy embedding backends (desktop/server only) ────────────────────────────
HAS_FASTEMBED = False
HAS_SENTENCE_TRANSFORMERS = False
_legacy_model = None

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

EMBED_MODEL_FASTEMBED = "BAAI/bge-small-en-v1.5"
EMBED_MODEL_ST        = "all-MiniLM-L6-v2"


def _get_legacy_model():
    global _legacy_model
    if _legacy_model is not None:
        return _legacy_model
    if HAS_FASTEMBED:
        _legacy_model = _FETextEmbedding(EMBED_MODEL_FASTEMBED)
    elif HAS_SENTENCE_TRANSFORMERS:
        _legacy_model = _STModel(EMBED_MODEL_ST)
    else:
        raise ImportError("No legacy embedding backend available.")
    return _legacy_model


def _encode_legacy(texts: list) -> "np.ndarray":
    model = _get_legacy_model()
    if HAS_FASTEMBED:
        return np.array(list(model.embed(texts)), dtype="float32")
    return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)


# ── Llama-server embedding backend ─────────────────────────────────────────────
# Uses the already-running llama-server. Every GGUF model supports /v1/embeddings.
# Detected lazily — no HTTP calls at import time.

# Port 8082 = dedicated nomic-embed server (Option C, v2.6.6).
# Falls back to CODEY_EMBED_PORT env var, then CODEY_LLAMA_PORT, then 8082.
_LLAMA_PORT = os.environ.get(
    "CODEY_EMBED_PORT",
    os.environ.get("CODEY_LLAMA_PORT", "8082"),
)
_LLAMA_EMBED_URL = f"http://localhost:{_LLAMA_PORT}/v1/embeddings"
_llama_ok: bool | None = None  # None = unchecked

# LRU cache for query embeddings — avoids re-embedding identical queries
_EMBED_CACHE_MAX = 20
_embed_cache: OrderedDict = OrderedDict()


def check_llama_embeddings() -> bool:
    """
    Check if llama-server /v1/embeddings is reachable and returns valid vectors.
    Result is cached after the first call — no repeated probes.
    """
    global _llama_ok
    if _llama_ok is not None:
        return _llama_ok
    if not _np_ok:
        _llama_ok = False
        return False
    try:
        import urllib.request as _req
        payload = json.dumps({"model": "local", "input": ["ping"]}).encode()
        request = _req.Request(
            _LLAMA_EMBED_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _req.urlopen(request, timeout=4) as resp:
            data = json.loads(resp.read())
        ok = (
            isinstance(data.get("data"), list)
            and len(data["data"]) > 0
            and "embedding" in data["data"][0]
            and len(data["data"][0]["embedding"]) > 0
        )
        _llama_ok = ok
    except Exception:
        _llama_ok = False
    return _llama_ok


def _embed_via_llama(texts: list, batch_size: int = 16) -> "np.ndarray":
    """
    Embed a list of texts via llama-server /v1/embeddings.

    Sends texts in batches of `batch_size` to reduce HTTP overhead.
    Returns shape (len(texts), embedding_dim) float32 array.

    Raises on HTTP or parse error — caller must handle.
    """
    import urllib.request as _req

    all_vecs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        payload = json.dumps({"model": "local", "input": batch}).encode()
        request = _req.Request(
            _LLAMA_EMBED_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _req.urlopen(request, timeout=60) as resp:
            data = json.loads(resp.read())
        # Sort by index to maintain original order
        for item in sorted(data["data"], key=lambda x: x["index"]):
            all_vecs.append(item["embedding"])

    return np.array(all_vecs, dtype="float32")


def _embed_query(query: str) -> "np.ndarray | None":
    """
    Embed a single query string, checking the LRU cache first.
    Returns None if llama-server is unavailable.
    """
    if query in _embed_cache:
        _embed_cache.move_to_end(query)
        return _embed_cache[query]

    if not check_llama_embeddings():
        return None

    try:
        vec = _embed_via_llama([query], batch_size=1)[0]
        _embed_cache[query] = vec
        _embed_cache.move_to_end(query)
        if len(_embed_cache) > _EMBED_CACHE_MAX:
            _embed_cache.popitem(last=False)
        return vec
    except Exception:
        return None


# ── BM25 (pure Python, Okapi BM25) ────────────────────────────────────────────

def _tokenize(text: str) -> list:
    import re
    return re.findall(r"[a-z0-9_]{2,}", text.lower())


class _BM25Index:
    """
    In-memory Okapi BM25 index.
    k1=1.5, b=0.75 — Elasticsearch/Lucene defaults.
    IDF uses Robertson formula: log((N - df + 0.5) / (df + 0.5) + 1).
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
            num = tf * (self.K1 + 1)
            den = tf + self.K1 * (1 - self.B + self.B * dl / max(self.avg_dl, 1))
            s += self.idf[w] * num / max(den, 1e-8)
        return s

    def search(self, query: str, top_k: int = 5) -> list:
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


# ── RRF merge ─────────────────────────────────────────────────────────────────

def _rrf_merge(result_lists: list, k: int = 60, top_n: int = 5) -> list:
    """
    Reciprocal Rank Fusion over multiple ranked result lists.

    RRF score = Σ 1 / (rank + k)  for each list the item appears in.
    k=60 is the standard constant (Cormack et al. 2009).

    No score normalization needed — only rank positions are used.
    Deduplicates by (source, text[:80]) key.

    Args:
        result_lists: Each list is [{text, source, score}, ...] in rank order.
        k:     RRF smoothing constant (default 60).
        top_n: Number of results to return.

    Returns:
        Merged, RRF-ranked list of up to top_n result dicts.
    """
    seen: dict = {}
    for result_list in result_lists:
        for rank, item in enumerate(result_list):
            key = (item.get("source", ""), item.get("text", "")[:80])
            contrib = 1.0 / (rank + k)
            if key in seen:
                seen[key]["rrf_score"] += contrib
            else:
                seen[key] = {"result": item, "rrf_score": contrib}

    ranked = sorted(seen.values(), key=lambda x: x["rrf_score"], reverse=True)
    return [entry["result"] for entry in ranked[:top_n]]


# ── Chunk loading ─────────────────────────────────────────────────────────────

def _load_all_chunks() -> list:
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


# ── Vector index: build + load ────────────────────────────────────────────────

def build_semantic_index() -> int:
    """
    Build a vector index over all indexed KB chunks.

    Backend priority:
      1. llama-server /v1/embeddings  — works on Termux, no new dependencies
      2. fastembed                    — ONNX, no torch (desktop/server only)
      3. sentence-transformers        — PyTorch (desktop/server only)

    Index is saved to knowledge/embeddings/:
      vectors.npy       — float32 array of shape (n_chunks, embed_dim)
      vectors.meta.json — backend name + dimension (for compatibility check)
      mapping.json      — chunk metadata in same row order as vectors.npy

    Returns number of embeddings built, or 0 if no backend is available.
    """
    all_chunks = _load_all_chunks()
    if not all_chunks:
        print("[kb_semantic] No chunks found. Run index_directory() first.")
        return 0

    texts = [c["text"] for c in all_chunks]
    chunk_dir = KB_ROOT / "embeddings"

    # Select backend
    if _np_ok and check_llama_embeddings():
        backend = "llama-server"
    elif _np_ok and HAS_FASTEMBED:
        backend = "fastembed"
    elif _np_ok and HAS_SENTENCE_TRANSFORMERS:
        backend = "sentence-transformers"
    else:
        print("[kb_semantic] No embedding backend available.")
        print("  BM25 keyword search is active — no setup needed on Termux.")
        print("  To enable semantic search:")
        print("    Ensure llama-server is running, then re-run setup_skills.sh")
        print("    (desktop: pip install fastembed)")
        return 0

    print(f"[kb_semantic] Embedding {len(texts)} chunks via {backend}...")

    try:
        if backend == "llama-server":
            all_vecs = []
            skipped = 0
            dim = None
            for i, text in enumerate(texts):
                try:
                    vec = _embed_via_llama([text], batch_size=1)[0]
                    all_vecs.append(vec)
                    if dim is None:
                        dim = len(vec)
                except Exception:
                    # Skip chunks that are too long or cause server errors
                    if dim is not None:
                        all_vecs.append([0.0] * dim)  # zero vector placeholder
                    skipped += 1
                if i % 200 == 0:
                    pct = int(100 * i / len(texts))
                    print(f"  {pct}%  ({i}/{len(texts)})")
            if skipped:
                print(f"  Warning: {skipped} chunks skipped (too long or error)")
            if not all_vecs:
                raise RuntimeError("No embeddings generated")
            embeddings = np.array(all_vecs, dtype="float32")
        else:
            embeddings = _encode_legacy(texts)
    except Exception as e:
        print(f"[kb_semantic] Embedding failed: {e}")
        return 0

    # Save vectors + metadata
    np.save(str(chunk_dir / "vectors.npy"), embeddings.astype("float32"))

    with open(chunk_dir / "vectors.meta.json", "w") as f:
        json.dump({
            "backend": backend,
            "dim":     int(embeddings.shape[1]),
            "count":   int(embeddings.shape[0]),
        }, f)

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

    dim = embeddings.shape[1]
    print(f"[kb_semantic] Done: {len(embeddings)} × {dim}d vectors saved ({backend})")
    return len(embeddings)


def repair_failed_embeddings() -> int:
    """
    Re-embed only the chunks that failed during build_semantic_index().

    Failed chunks were stored as zero vectors (all 0.0).  This function
    finds those rows, re-embeds the corresponding text via llama-server,
    and writes the updated vectors.npy back to disk.

    Returns the number of chunks successfully repaired, or -1 on error.

    Usage:
        python3 -c "from tools.kb_semantic import repair_failed_embeddings; repair_failed_embeddings()"
    """
    if not _np_ok:
        print("[kb_semantic] numpy not available — cannot repair embeddings")
        return -1

    chunk_dir = KB_ROOT / "embeddings"
    vp = chunk_dir / "vectors.npy"
    mp = chunk_dir / "mapping.json"

    if not vp.exists() or not mp.exists():
        print("[kb_semantic] No existing index found — run build_semantic_index() first")
        return -1

    vectors = np.load(str(vp))
    with open(mp, encoding="utf-8") as f:
        mapping = json.load(f)

    if len(vectors) != len(mapping):
        print(f"[kb_semantic] Index mismatch: {len(vectors)} vectors vs {len(mapping)} mapping entries")
        return -1

    # Find zero-vector rows (norm == 0.0)
    norms = np.linalg.norm(vectors, axis=1)
    failed_indices = [i for i, n in enumerate(norms) if n == 0.0]

    if not failed_indices:
        print("[kb_semantic] No failed chunks found — index is already complete")
        return 0

    print(f"[kb_semantic] Found {len(failed_indices)} zero-vector chunks to repair...")

    if not check_llama_embeddings():
        print("[kb_semantic] llama-server not reachable — start embed server first")
        return -1

    repaired = 0
    still_failed = 0
    for i, idx in enumerate(failed_indices):
        text = mapping[idx].get("text", "")
        if not text:
            still_failed += 1
            continue
        try:
            vec = _embed_via_llama([text], batch_size=1)[0]
            vectors[idx] = vec
            repaired += 1
        except Exception as e:
            still_failed += 1
        if (i + 1) % 100 == 0 or (i + 1) == len(failed_indices):
            pct = int(100 * (i + 1) / len(failed_indices))
            print(f"  {pct}%  ({i + 1}/{len(failed_indices)}) repaired={repaired} failed={still_failed}")

    # Save updated vectors
    np.save(str(vp), vectors.astype("float32"))

    # Update meta count (dim unchanged)
    mep = chunk_dir / "vectors.meta.json"
    if mep.exists():
        with open(mep) as f:
            meta = json.load(f)
        meta["repaired"] = repaired
        meta["still_zero"] = still_failed
        with open(mep, "w") as f:
            json.dump(meta, f)

    print(f"[kb_semantic] Repair done: {repaired} fixed, {still_failed} still zero")
    return repaired


def _load_vector_index() -> tuple:
    """
    Load pre-built vector index from disk.
    Returns (vectors, mapping, meta) or (None, None, {}) if not available.
    """
    chunk_dir = KB_ROOT / "embeddings"
    vp = chunk_dir / "vectors.npy"
    mp = chunk_dir / "mapping.json"
    if not vp.exists() or not mp.exists():
        return None, None, {}
    try:
        vectors = np.load(str(vp))
        with open(mp, encoding="utf-8") as f:
            mapping = json.load(f)
        meta = {}
        mep = chunk_dir / "vectors.meta.json"
        if mep.exists():
            with open(mep) as f:
                meta = json.load(f)
        return vectors, mapping, meta
    except Exception:
        return None, None, {}


# ── Public search API ─────────────────────────────────────────────────────────

def semantic_search(query: str, top_k: int = 5) -> list:
    """
    Search the knowledge base with the best available strategy.

    If a vector index exists AND the query can be embedded (llama-server
    running, or legacy backend matches index backend), returns hybrid
    BM25 + vector results merged via RRF.

    Falls back to BM25-only silently if vector search is unavailable.

    Args:
        query:  Search query string.
        top_k:  Number of results to return.

    Returns:
        List of {text, source, score} dicts, best first.
    """
    # Over-fetch for RRF — each list gets 3× top_k candidates
    candidate_k = top_k * 3

    bm25_results = keyword_fallback(query, top_k=candidate_k)

    if not _np_ok:
        return bm25_results[:top_k]

    vectors, mapping, meta = _load_vector_index()
    if vectors is None or not mapping:
        return bm25_results[:top_k]

    # Only use vector search if query can be embedded with the same backend
    # that built the index (avoids dimension mismatch).
    index_backend = meta.get("backend", "unknown")
    q_vec = None

    if index_backend == "llama-server":
        q_vec = _embed_query(query)  # uses LRU cache + lazy check
    elif index_backend in ("fastembed", "sentence-transformers"):
        if HAS_FASTEMBED or HAS_SENTENCE_TRANSFORMERS:
            try:
                q_arr = _encode_legacy([query])
                q_vec = q_arr[0]
            except Exception:
                pass

    if q_vec is None:
        # Index backend unavailable for query — BM25 only
        return bm25_results[:top_k]

    try:
        norms = np.linalg.norm(vectors, axis=1)
        q_norm = float(np.linalg.norm(q_vec))
        if q_norm < 1e-8:
            return bm25_results[:top_k]

        sims = np.dot(vectors, q_vec) / (norms * q_norm + 1e-8)
        top_idx = np.argsort(sims)[-candidate_k:][::-1]

        vector_results = []
        for i in top_idx:
            if i < len(mapping):
                m = mapping[int(i)]
                vector_results.append({
                    "text":   m["text"],
                    "source": m.get("source", m.get("filename", "")),
                    "score":  float(sims[i]),
                })

        if not vector_results:
            return bm25_results[:top_k]

        return _rrf_merge([bm25_results, vector_results], top_n=top_k)

    except Exception:
        return bm25_results[:top_k]


def keyword_fallback(query: str, top_k: int = 5) -> list:
    """
    BM25 search over all indexed chunks. Zero dependencies, always active.

    Uses Okapi BM25 (k1=1.5, b=0.75) — same algorithm as Elasticsearch.

    Args:
        query:  Search query string.
        top_k:  Number of results to return.

    Returns:
        List of {text, source, score} dicts, best first.
    """
    all_chunks = _load_all_chunks()
    if not all_chunks:
        return []
    return _BM25Index(all_chunks).search(query, top_k=top_k)


def has_index() -> bool:
    """Return True if the KB has any indexed chunk files."""
    chunk_dir = KB_ROOT / "embeddings"
    if not chunk_dir.exists():
        return False
    return any(chunk_dir.glob("*.chunks.json"))


def index_stats() -> dict:
    """Return a status dict for display in /status or setup output."""
    chunk_dir = KB_ROOT / "embeddings"
    if not chunk_dir.exists():
        return {
            "chunk_files": 0, "total_chunks": 0,
            "has_semantic": False, "backend": "none",
            "kb_root": str(KB_ROOT),
        }

    chunk_files = list(chunk_dir.glob("*.chunks.json"))
    total = 0
    for cf in chunk_files:
        try:
            with open(cf) as f:
                total += len(json.load(f))
        except Exception:
            pass

    has_vec = (chunk_dir / "vectors.npy").exists()
    meta = {}
    mep = chunk_dir / "vectors.meta.json"
    if mep.exists():
        try:
            with open(mep) as f:
                meta = json.load(f)
        except Exception:
            pass

    index_backend = meta.get("backend", "unknown") if has_vec else None
    dim = meta.get("dim", "?") if has_vec else None

    if has_vec and index_backend == "llama-server":
        backend = f"hybrid BM25 + llama-embeddings ({dim}d, RRF)"
    elif has_vec and index_backend == "fastembed":
        backend = f"hybrid BM25 + fastembed ({dim}d, RRF)"
    elif has_vec and index_backend == "sentence-transformers":
        backend = f"hybrid BM25 + sentence-transformers ({dim}d, RRF)"
    elif HAS_FASTEMBED:
        backend = "fastembed available (run build_semantic_index)"
    elif HAS_SENTENCE_TRANSFORMERS:
        backend = "sentence-transformers available (run build_semantic_index)"
    else:
        backend = "BM25 keyword (no vector index — run setup_skills.sh with llama-server active)"

    return {
        "chunk_files":            len(chunk_files),
        "total_chunks":           total,
        "has_semantic":           has_vec,
        "backend":                backend,
        "llama_embed_available":  check_llama_embeddings(),
        "sentence_transformers":  HAS_SENTENCE_TRANSFORMERS,
        "kb_root":                str(KB_ROOT),
    }
