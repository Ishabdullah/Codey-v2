"""
SQLite metadata store — persists full output records keyed by vector ID.

Schema:
  records(
    id          INTEGER PRIMARY KEY,   -- matches hnswlib vector ID
    record_id   TEXT UNIQUE,           -- sha256[:16] of user text
    user        TEXT,
    tool_calls  TEXT,                  -- JSON
    metadata    TEXT,                  -- JSON
    embed_text  TEXT,                  -- text that was embedded
    created_at  INTEGER
  )
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional


class SQLiteMetadataStore:
    """
    Stores and retrieves Codey-v2 output records by vector index ID.

    Args:
        db_path: Path to the SQLite database file
    """

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id          INTEGER PRIMARY KEY,
                record_id   TEXT UNIQUE NOT NULL,
                user        TEXT NOT NULL,
                tool_calls  TEXT NOT NULL,
                metadata    TEXT NOT NULL,
                embed_text  TEXT NOT NULL,
                created_at  INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_record_id ON records(record_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source    ON records(json_extract(metadata, '$.source'))")
        conn.commit()

    def insert(self, vector_id: int, record: Dict, embed_text: str) -> None:
        """Insert or replace a record."""
        conn = self._connect()
        meta = record.get("metadata", {})
        conn.execute(
            """
            INSERT OR REPLACE INTO records
                (id, record_id, user, tool_calls, metadata, embed_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vector_id,
                meta.get("id", ""),
                record.get("user", ""),
                json.dumps(record.get("tool_calls", []), ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
                embed_text,
                int(time.time()),
            ),
        )
        conn.commit()

    def insert_batch(self, items: List[tuple]) -> None:
        """
        Batch insert.

        Args:
            items: List of (vector_id, record, embed_text) tuples
        """
        conn = self._connect()
        rows = []
        for vector_id, record, embed_text in items:
            meta = record.get("metadata", {})
            rows.append((
                vector_id,
                meta.get("id", ""),
                record.get("user", ""),
                json.dumps(record.get("tool_calls", []), ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
                embed_text,
                int(time.time()),
            ))
        conn.executemany(
            """
            INSERT OR REPLACE INTO records
                (id, record_id, user, tool_calls, metadata, embed_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    def get_by_vector_id(self, vector_id: int) -> Optional[Dict]:
        """Retrieve a full record by its vector index ID."""
        conn = self._connect()
        row  = conn.execute(
            "SELECT * FROM records WHERE id = ?", (vector_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_ids(self, vector_ids: List[int]) -> List[Optional[Dict]]:
        """Retrieve multiple records by vector IDs (preserves order)."""
        if not vector_ids:
            return []
        conn = self._connect()
        placeholders = ",".join("?" * len(vector_ids))
        rows = conn.execute(
            f"SELECT * FROM records WHERE id IN ({placeholders})", vector_ids
        ).fetchall()
        id_map = {row["id"]: self._row_to_dict(row) for row in rows}
        return [id_map.get(vid) for vid in vector_ids]

    def count(self) -> int:
        conn = self._connect()
        return conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _row_to_dict(row) -> Dict:
        return {
            "vector_id":  row["id"],
            "record_id":  row["record_id"],
            "user":       row["user"],
            "tool_calls": json.loads(row["tool_calls"]),
            "metadata":   json.loads(row["metadata"]),
            "embed_text": row["embed_text"],
        }
