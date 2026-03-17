"""
Knowledge Base Chunk Indexer — Phase 1 (v2.6.1)

Splits documents into overlapping chunks and writes .chunks.json index files
to knowledge/embeddings/. Used by core/retrieval.py for RAG retrieval.

Usage:
    from tools.kb_scraper import index_file, index_directory, KB_ROOT

    # Index a single file
    index_file("docs/flask_guide.md", category="flask")

    # Index an entire directory
    index_directory("knowledge/docs", category="docs")
"""

import os
import json
import hashlib
from pathlib import Path

# ── KB root — resolved from env var so it works wherever codey-v2 lives ──────
KB_ROOT = Path(os.environ.get("CODEY_DIR", Path.home() / "codey-v2")) / "knowledge"

# Chunk tuning — 512 words ≈ ~680 tokens (fits within retrieval budget)
CHUNK_SIZE = 512       # words per chunk
CHUNK_OVERLAP = 64     # overlap between adjacent chunks for continuity

# Extensions to index by default
DEFAULT_EXTENSIONS = (".md", ".txt", ".py", ".rst", ".yaml", ".yml", ".json")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """
    Split text into overlapping chunks with stable IDs.

    Args:
        text: Raw document text
        chunk_size: Max words per chunk
        overlap: Word overlap between adjacent chunks

    Returns:
        List of dicts: {id, text, start_word, end_word}
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        # Stable ID: MD5 of first 100 chars — deterministic across re-index runs
        chunk_id = hashlib.md5(chunk[:100].encode("utf-8", errors="replace")).hexdigest()[:12]
        chunks.append({
            "id": chunk_id,
            "text": chunk,
            "start_word": start,
            "end_word": end,
        })
        if end == len(words):
            break
        start += chunk_size - overlap

    return chunks


def index_file(filepath: str, category: str = "docs") -> list:
    """
    Read a file, chunk it, write chunk index to knowledge/embeddings/.

    Args:
        filepath: Path to the file to index
        category: Category label (e.g. "docs", "flask", "skill:superpowers")

    Returns:
        List of chunk dicts (empty on failure)
    """
    path = Path(filepath)
    if not path.exists() or not path.is_file():
        return []

    # Skip binary files
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    if not text.strip():
        return []

    chunks = chunk_text(text)

    # Tag each chunk with source metadata
    for chunk in chunks:
        chunk["source"] = str(path.resolve())
        chunk["category"] = category
        chunk["filename"] = path.name

    # Write chunk index to knowledge/embeddings/<stem>.chunks.json
    embed_dir = KB_ROOT / "embeddings"
    embed_dir.mkdir(parents=True, exist_ok=True)

    # Use a sanitised stem to avoid collisions (replace / with _)
    safe_stem = path.stem.replace("/", "_").replace("\\", "_")
    # If multiple files have the same stem, include a hash of the full path
    path_hash = hashlib.md5(str(path.resolve()).encode()).hexdigest()[:6]
    index_path = embed_dir / f"{safe_stem}_{path_hash}.chunks.json"

    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)
    except Exception:
        return []

    return chunks


def index_directory(
    dirpath: str,
    category: str = "docs",
    extensions: tuple = DEFAULT_EXTENSIONS,
    max_files: int = 500,
) -> int:
    """
    Index all matching files in a directory recursively.

    Args:
        dirpath: Root directory to scan
        category: Category label for all files
        extensions: File extensions to include
        max_files: Safety cap (prevents runaway indexing of huge repos)

    Returns:
        Total number of chunks indexed
    """
    root = Path(dirpath)
    if not root.is_dir():
        print(f"[kb_scraper] Not a directory: {dirpath}")
        return 0

    total_chunks = 0
    files_indexed = 0

    for path in sorted(root.rglob("*")):
        if files_indexed >= max_files:
            print(f"[kb_scraper] Reached max_files={max_files}, stopping.")
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        # Skip hidden dirs and common noise
        parts = path.parts
        if any(p.startswith(".") or p in ("__pycache__", "node_modules", ".git") for p in parts):
            continue

        chunks = index_file(str(path), category)
        if chunks:
            total_chunks += len(chunks)
            files_indexed += 1
            print(f"  [kb_scraper] {path.name}: {len(chunks)} chunks")

    print(f"[kb_scraper] Total: {total_chunks} chunks from {files_indexed} files in {dirpath}")
    return total_chunks


def list_indexed() -> list:
    """Return list of all indexed chunk files in knowledge/embeddings/."""
    embed_dir = KB_ROOT / "embeddings"
    if not embed_dir.exists():
        return []
    return sorted(str(p) for p in embed_dir.glob("*.chunks.json"))


def count_chunks() -> int:
    """Return total number of indexed chunks across all files."""
    total = 0
    for chunk_file in (KB_ROOT / "embeddings").glob("*.chunks.json"):
        try:
            with open(chunk_file) as f:
                total += len(json.load(f))
        except Exception:
            pass
    return total
