"""
EmbeddingPipeline — builds embed_text strings and generates vectors.

Primary:  nomic-embed-text on port 8082 (768-dim)
Fallback: sentence-transformers all-MiniLM-L6-v2 (384-dim)
"""

from typing import Dict, List, Optional, Tuple
from .nomic_client    import NomicEmbedClient
from .sentence_client import SentenceEmbedClient


# Batch size: how many texts to embed per HTTP/inference call
_BATCH_SIZE = 64


def build_embed_text(record: Dict) -> str:
    """
    Construct the text that will be embedded for a given output record.

    Format: "{user} → {tool_name} {primary_arg_value}"

    This encodes both the intent (user) and the resolution (tool + key arg)
    so that similarity search retrieves examples with matching *actions*,
    not just matching questions.
    """
    user       = record.get("user", "").strip()
    tool_calls = record.get("tool_calls", [])

    if not tool_calls:
        return user

    parts = []
    for tc in tool_calls:
        name = tc.get("name", "")
        args = tc.get("args", {})

        # Pick the most informative arg value for each tool
        primary = ""
        if name == "shell":
            primary = args.get("command", "")[:80]
        elif name in ("write_file", "patch_file", "read_file", "append_file"):
            primary = args.get("path", "")
        elif name == "search_files":
            primary = args.get("pattern", "")
        elif name == "note_save":
            primary = args.get("key", "")
        elif name == "list_dir":
            primary = args.get("path", ".")

        if primary:
            parts.append(f"{name} {primary}")
        else:
            parts.append(name)

    action_str = " | ".join(parts)
    return f"{user} → {action_str}"


class EmbeddingPipeline:
    """
    Embeds output records in batches.

    Auto-selects nomic server if available, falls back to sentence-transformers.

    Args:
        nomic_port:   Port for nomic embed server (default 8082)
        batch_size:   Records per embedding call (default 64)
        force_local:  Skip nomic server and always use sentence-transformers
    """

    def __init__(
        self,
        nomic_port: int = 8082,
        batch_size: int = _BATCH_SIZE,
        force_local: bool = False,
    ):
        self.batch_size  = batch_size
        self._nomic      = NomicEmbedClient(port=nomic_port)
        self._local      = SentenceEmbedClient()
        self._backend    = None
        self._dim: Optional[int] = None
        self._force_local = force_local

    # ── Backend selection ─────────────────────────────────────────────────────

    def _get_backend(self):
        if self._backend is not None:
            return self._backend

        if not self._force_local and self._nomic.is_available():
            self._backend = self._nomic
            self._dim     = 768
        elif self._local.is_available():
            self._backend = self._local
            self._dim     = self._local.dim
        else:
            raise RuntimeError(
                "No embedding backend available. "
                "Start nomic server (port 8082) or install sentence-transformers."
            )

        return self._backend

    @property
    def dim(self) -> int:
        self._get_backend()
        return self._dim or 384

    @property
    def backend_name(self) -> str:
        b = self._get_backend()
        return "nomic" if isinstance(b, NomicEmbedClient) else "sentence-transformers"

    # ── Embedding ─────────────────────────────────────────────────────────────

    def embed_record(self, record: Dict) -> Optional[List[float]]:
        """Embed a single output record. Returns None on failure."""
        text = build_embed_text(record)
        backend = self._get_backend()
        return backend.embed(text)

    def embed_records(
        self,
        records: List[Dict],
        progress: bool = True,
    ) -> List[Tuple[Dict, Optional[List[float]]]]:
        """
        Embed a list of output records in batches.

        Args:
            records:  List of output records
            progress: Print batch progress to stdout

        Returns:
            List of (record, vector) tuples. Vector is None on failure.
        """
        backend = self._get_backend()
        results = []
        total   = len(records)

        for batch_start in range(0, total, self.batch_size):
            batch   = records[batch_start: batch_start + self.batch_size]
            texts   = [build_embed_text(r) for r in batch]
            vectors = backend.embed_batch(texts)

            for record, vec in zip(batch, vectors):
                results.append((record, vec))

            if progress:
                done = min(batch_start + self.batch_size, total)
                print(f"  Embedded {done}/{total} records", end="\r", flush=True)

        if progress:
            print()

        return results
