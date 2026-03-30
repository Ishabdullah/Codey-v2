"""
Local JSONL ingestor — for synthetic corpora and custom datasets.
"""

import json
from pathlib import Path
from typing import Iterator, Dict, Optional
from .base import BaseIngestor


class JSONLIngestor(BaseIngestor):
    """
    Yield records from a local .jsonl file.

    Expects each line to be a valid JSON object. Lines starting with '#'
    are treated as comments and skipped.

    Args:
        path:          Path to the .jsonl file
        schema_type:   Schema type tag (default: "jsonl_generic")
        max_records:   Stop after this many records
    """

    def __init__(
        self,
        path: str,
        schema_type: str = "jsonl_generic",
        max_records: Optional[int] = None,
    ):
        self.path = Path(path)
        self._schema_type = schema_type
        self.max_records = max_records

        if not self.path.exists():
            raise FileNotFoundError(f"JSONL file not found: {path}")

    def name(self) -> str:
        return self.path.stem

    @property
    def schema_type(self) -> str:
        return self._schema_type

    def ingest(self) -> Iterator[Dict]:
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if self.max_records is not None and count >= self.max_records:
                    break
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record["_source"] = str(self.path)
                record["_schema_type"] = self._schema_type
                yield record
                count += 1
