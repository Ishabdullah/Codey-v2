#!/usr/bin/env python3
"""
Core state store for Codey-v2.

SQLite-backed persistent storage for:
- General state (key-value)
- Task queue (pending/running/done/failed tasks)
- Episodic log (append-only action history)

Used by the daemon to persist state across restarts.
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional, Any, List, Dict
from threading import Lock

from utils.config import CODEY_DIR

# State directory and database path (Codey-v2 specific)
STATE_DIR = Path.home() / ".codey-v2"
STATE_DB = STATE_DIR / "state.db"

# Ensure state directory exists
STATE_DIR.mkdir(parents=True, exist_ok=True)


class StateStore:
    """
    SQLite-backed state store with persistent connection.

    Thread-safe via internal lock. The connection is opened once at
    construction time and reused for all operations, eliminating the
    per-call open/close overhead.
    """

    def __init__(self, db_path: Path = STATE_DB):
        self.db_path = db_path
        self._lock = Lock()
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read performance
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self):
        """Close the persistent connection."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def _init_schema(self):
        """Initialize database schema if not exists."""
        with self._lock:
            cur = self._conn.cursor()

            # State table (key-value store)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)

            # Task queue table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS task_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    created_at INTEGER NOT NULL,
                    started_at INTEGER,
                    completed_at INTEGER,
                    dependencies TEXT DEFAULT '[]',
                    retry_count INTEGER DEFAULT 0
                )
            """)
            # Add columns to existing DBs that predate this schema version
            for col, defn in [
                ("dependencies", "TEXT DEFAULT '[]'"),
                ("retry_count",  "INTEGER DEFAULT 0"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE task_queue ADD COLUMN {col} {defn}")
                except sqlite3.OperationalError:
                    pass  # column already exists

            # Episodic log table (append-only action history)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS episodic_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT
                )
            """)

            # Model state table (Phase 3)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS model_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    active_model TEXT NOT NULL,
                    loaded_at INTEGER NOT NULL,
                    last_swap_at INTEGER,
                    swap_count INTEGER DEFAULT 0
                )
            """)

            # Project files table (Phase 4)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS project_files (
                    path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    loaded_at INTEGER NOT NULL,
                    is_protected INTEGER NOT NULL
                )
            """)

            # Working memory table (Phase 4)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS working_memory (
                    file_path TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    loaded_at INTEGER NOT NULL,
                    last_used_at INTEGER NOT NULL
                )
            """)

            # Checkpoints table (Phase 6)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    id TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    files_modified TEXT,
                    git_commit_hash TEXT
                )
            """)

            self._conn.commit()

    # ==================== State (Key-Value) ====================

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from state by key."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT value FROM state WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else default

    def set(self, key: str, value: Any):
        """Set a value in state."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, str(value), int(time.time())),
            )
            self._conn.commit()

    def delete(self, key: str) -> bool:
        """Delete a key from state. Returns True if deleted, False if not found."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM state WHERE key = ?", (key,))
            self._conn.commit()
            return cur.rowcount > 0

    def get_all(self) -> Dict[str, str]:
        """Get all state key-value pairs."""
        with self._lock:
            cur = self._conn.execute("SELECT key, value FROM state")
            return {row["key"]: row["value"] for row in cur.fetchall()}

    # ==================== Task Queue ====================

    def add_task(self, description: str, dependencies: list = None) -> int:
        """Add a task to the queue. Returns task ID."""
        import json
        deps = json.dumps(dependencies or [])
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO task_queue (description, status, created_at, dependencies) VALUES (?, 'pending', ?, ?)",
                (description, int(time.time()), deps),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_task(self, task_id: int) -> Optional[Dict]:
        """Get a task by ID."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM task_queue WHERE id = ?", (task_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_next_pending(self) -> Optional[Dict]:
        """Get the next pending task whose dependencies are all done (oldest first).

        Uses a single SQL query with NOT EXISTS to avoid nested cursor access on
        the same connection, which can cause 'ProgrammingError: Recursive use of
        cursors not allowed' on some SQLite builds.
        """
        import json
        with self._lock:
            # Fetch all pending tasks ordered oldest-first in one shot
            rows = self._conn.execute(
                "SELECT * FROM task_queue WHERE status = 'pending' ORDER BY created_at ASC"
            ).fetchall()

        # Dependency checks are done outside the lock using independent queries
        for row in rows:
            task = dict(row)
            deps = json.loads(task.get("dependencies") or "[]")
            if not deps:
                return task
            # Check every dependency is done
            all_done = True
            with self._lock:
                for dep_id in deps:
                    dep_row = self._conn.execute(
                        "SELECT status FROM task_queue WHERE id = ?", (dep_id,)
                    ).fetchone()
                    if not dep_row or dep_row["status"] != "done":
                        all_done = False
                        break
            if all_done:
                return task
        return None

    def try_claim_task(self, task_id: int) -> bool:
        """Atomically mark a task as running only if it is currently pending.

        Returns True if this caller successfully claimed the task (rowcount == 1).
        Returns False if the task was already running/done/failed (claimed elsewhere).
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE task_queue SET status = 'running', started_at = ?"
                " WHERE id = ? AND status = 'pending'",
                (int(time.time()), task_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def start_task(self, task_id: int):
        """Mark a task as running."""
        with self._lock:
            self._conn.execute(
                "UPDATE task_queue SET status = 'running', started_at = ? WHERE id = ?",
                (int(time.time()), task_id),
            )
            self._conn.commit()

    def complete_task(self, task_id: int, result: str = None):
        """Mark a task as completed."""
        with self._lock:
            self._conn.execute(
                "UPDATE task_queue SET status = 'done', result = ?, completed_at = ? WHERE id = ?",
                (result, int(time.time()), task_id),
            )
            self._conn.commit()

    def fail_task(self, task_id: int, error: str):
        """Mark a task as failed."""
        with self._lock:
            self._conn.execute(
                "UPDATE task_queue SET status = 'failed', result = ?, completed_at = ? WHERE id = ?",
                (error, int(time.time()), task_id),
            )
            self._conn.commit()

    def increment_retry(self, task_id: int):
        """Increment retry_count for a task."""
        with self._lock:
            self._conn.execute(
                "UPDATE task_queue SET retry_count = retry_count + 1 WHERE id = ?",
                (task_id,),
            )
            self._conn.commit()

    def cancel_task(self, task_id: int) -> bool:
        """
        Cancel a task (pending or running).
        Returns True if cancelled, False if already done/failed.
        """
        task = self.get_task(task_id)
        if not task or task["status"] in ("done", "failed"):
            return False
        # Mark cancellation flag so executor can detect it
        self.set(f"task_cancelled_{task_id}", "1")
        if task["status"] == "running":
            with self._lock:
                self._conn.execute(
                    "UPDATE task_queue SET status = 'failed', result = ?, completed_at = ? WHERE id = ?",
                    ("Cancelled by user", int(time.time()), task_id),
                )
                self._conn.commit()
        return True

    def get_tasks_by_status(self, status: str) -> List[Dict]:
        """Get all tasks with a given status."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM task_queue WHERE status = ?", (status,))
            return [dict(row) for row in cur.fetchall()]

    def get_all_tasks(self) -> List[Dict]:
        """Get all tasks ordered by creation time."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM task_queue ORDER BY created_at DESC")
            return [dict(row) for row in cur.fetchall()]

    # ==================== Episodic Log ====================

    def log_action(self, action: str, details: str = None):
        """Log an action to the episodic log."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO episodic_log (timestamp, action, details) VALUES (?, ?, ?)",
                (int(time.time()), action, details),
            )
            self._conn.commit()

    def get_recent_actions(self, limit: int = 50) -> List[Dict]:
        """Get recent actions from the episodic log."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM episodic_log ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_actions_since(self, timestamp: int) -> List[Dict]:
        """Get actions since a given timestamp."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM episodic_log WHERE timestamp >= ? ORDER BY timestamp ASC",
                (timestamp,),
            )
            return [dict(row) for row in cur.fetchall()]

    def clear_old_actions(self, keep_hours: int = 24):
        """Remove actions older than keep_hours."""
        with self._lock:
            cutoff = int(time.time()) - (keep_hours * 3600)
            cur = self._conn.execute("DELETE FROM episodic_log WHERE timestamp < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    # ==================== Model State (Phase 3) ====================

    def save_model_state(self, active_model: str, swap_count: int = 0):
        """Save current model state."""
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO model_state (id, active_model, loaded_at, last_swap_at, swap_count) VALUES (1, ?, ?, ?, ?)",
                (active_model, now, now, swap_count),
            )
            self._conn.commit()

    def get_model_state(self) -> dict:
        """Get current model state."""
        with self._lock:
            cur = self._conn.execute("SELECT * FROM model_state WHERE id = 1")
            row = cur.fetchone()
            if row is None:
                return {"active_model": "primary", "loaded_at": 0, "last_swap_at": 0, "swap_count": 0}
            return dict(row)

    def update_model_swap(self, active_model: str, swap_count: int):
        """Update model swap tracking."""
        now = int(time.time())
        with self._lock:
            self._conn.execute(
                "UPDATE model_state SET active_model = ?, last_swap_at = ?, swap_count = ? WHERE id = 1",
                (active_model, now, swap_count),
            )
            self._conn.commit()

    # ==================== Checkpoints (Phase 6) ====================

    def get_checkpoints(self, limit: int = 10) -> List[Dict]:
        """Get recent checkpoints."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM checkpoints ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            return [dict(row) for row in cur.fetchall()]

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict]:
        """Get a specific checkpoint."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM checkpoints WHERE id = ?", (checkpoint_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def execute(self, sql: str, params: tuple = None):
        """Execute arbitrary SQL (for schema extensions)."""
        with self._lock:
            if params:
                self._conn.execute(sql, params)
            else:
                self._conn.execute(sql)
            self._conn.commit()


# Global state store instance (singleton)
_state_store: Optional[StateStore] = None


def get_state_store() -> StateStore:
    """Get the global state store instance."""
    global _state_store
    if _state_store is None:
        _state_store = StateStore()
    return _state_store


def reset_state_store():
    """Reset the global state store (for testing)."""
    global _state_store
    if _state_store:
        _state_store.close()
        _state_store = None
