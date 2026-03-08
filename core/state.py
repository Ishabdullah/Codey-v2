#!/usr/bin/env python3
"""
Core state store for Codey v2.

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

# State directory and database path (Codey v2 specific)
STATE_DIR = Path.home() / ".codey-v2"
STATE_DB = STATE_DIR / "state.db"

# Ensure state directory exists
STATE_DIR.mkdir(parents=True, exist_ok=True)


class StateStore:
    """
    SQLite-backed state store with get/set/delete methods.
    
    Thread-safe via internal lock.
    """
    
    def __init__(self, db_path: Path = STATE_DB):
        self.db_path = db_path
        self._lock = Lock()
        self._init_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_schema(self):
        """Initialize database schema if not exists."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # State table (key-value store)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                """)
                
                # Task queue table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS task_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        description TEXT NOT NULL,
                        status TEXT NOT NULL,
                        result TEXT,
                        created_at INTEGER NOT NULL,
                        started_at INTEGER,
                        completed_at INTEGER
                    )
                """)
                
                # Episodic log table (append-only action history)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS episodic_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp INTEGER NOT NULL,
                        action TEXT NOT NULL,
                        details TEXT
                    )
                """)

                # Model state table (Phase 3)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS model_state (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        active_model TEXT NOT NULL,
                        loaded_at INTEGER NOT NULL,
                        last_swap_at INTEGER,
                        swap_count INTEGER DEFAULT 0
                    )
                """)

                # Project files table (Phase 4)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS project_files (
                        path TEXT PRIMARY KEY,
                        content_hash TEXT NOT NULL,
                        loaded_at INTEGER NOT NULL,
                        is_protected INTEGER NOT NULL
                    )
                """)

                # Working memory table (Phase 4)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS working_memory (
                        file_path TEXT PRIMARY KEY,
                        content TEXT NOT NULL,
                        loaded_at INTEGER NOT NULL,
                        last_used_at INTEGER NOT NULL
                    )
                """)

                # Checkpoints table (Phase 6)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        id TEXT PRIMARY KEY,
                        created_at INTEGER NOT NULL,
                        reason TEXT NOT NULL,
                        files_modified TEXT,
                        git_commit_hash TEXT
                    )
                """)

                conn.commit()
            finally:
                conn.close()
    
    # ==================== State (Key-Value) ====================
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from state by key."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM state WHERE key = ?", (key,))
                row = cursor.fetchone()
                if row is None:
                    return default
                return row["value"]
            finally:
                conn.close()
    
    def set(self, key: str, value: Any):
        """Set a value in state."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO state (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, str(value), int(time.time())))
                conn.commit()
            finally:
                conn.close()
    
    def delete(self, key: str) -> bool:
        """Delete a key from state. Returns True if deleted, False if not found."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM state WHERE key = ?", (key,))
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
            finally:
                conn.close()
    
    def get_all(self) -> Dict[str, str]:
        """Get all state key-value pairs."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM state")
                return {row["key"]: row["value"] for row in cursor.fetchall()}
            finally:
                conn.close()
    
    # ==================== Task Queue ====================
    
    def add_task(self, description: str) -> int:
        """Add a task to the queue. Returns task ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO task_queue (description, status, created_at)
                    VALUES (?, 'pending', ?)
                """, (description, int(time.time())))
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()
    
    def get_task(self, task_id: int) -> Optional[Dict]:
        """Get a task by ID."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM task_queue WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                return dict(row)
            finally:
                conn.close()
    
    def get_next_pending(self) -> Optional[Dict]:
        """Get the next pending task (oldest first)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM task_queue 
                    WHERE status = 'pending' 
                    ORDER BY created_at ASC 
                    LIMIT 1
                """)
                row = cursor.fetchone()
                if row is None:
                    return None
                return dict(row)
            finally:
                conn.close()
    
    def start_task(self, task_id: int):
        """Mark a task as running."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE task_queue 
                    SET status = 'running', started_at = ?
                    WHERE id = ?
                """, (int(time.time()), task_id))
                conn.commit()
            finally:
                conn.close()
    
    def complete_task(self, task_id: int, result: str = None):
        """Mark a task as completed."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE task_queue 
                    SET status = 'done', result = ?, completed_at = ?
                    WHERE id = ?
                """, (result, int(time.time()), task_id))
                conn.commit()
            finally:
                conn.close()
    
    def fail_task(self, task_id: int, error: str):
        """Mark a task as failed."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE task_queue 
                    SET status = 'failed', result = ?, completed_at = ?
                    WHERE id = ?
                """, (error, int(time.time()), task_id))
                conn.commit()
            finally:
                conn.close()
    
    def cancel_task(self, task_id: int) -> bool:
        """
        Cancel a task (pending or running).
        Returns True if cancelled, False if already done/failed.
        """
        task = self.get_task(task_id)
        if not task:
            return False
        
        if task["status"] in ("done", "failed"):
            return False
        
        # Mark as cancelled in state (executor checks this)
        self.set(f"task_cancelled_{task_id}", "1")
        
        # If running, also mark in task_queue
        if task["status"] == "running":
            with self._lock:
                conn = self._get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE task_queue 
                        SET status = 'failed', result = ?, completed_at = ?
                        WHERE id = ?
                    """, ("Cancelled by user", int(time.time()), task_id))
                    conn.commit()
                finally:
                    conn.close()
        
        return True
    
    def get_tasks_by_status(self, status: str) -> List[Dict]:
        """Get all tasks with a given status."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM task_queue WHERE status = ?", (status,))
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()
    
    def get_all_tasks(self) -> List[Dict]:
        """Get all tasks ordered by creation time."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM task_queue ORDER BY created_at DESC")
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()
    
    # ==================== Episodic Log ====================
    
    def log_action(self, action: str, details: str = None):
        """Log an action to the episodic log."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO episodic_log (timestamp, action, details)
                    VALUES (?, ?, ?)
                """, (int(time.time()), action, details))
                conn.commit()
            finally:
                conn.close()
    
    def get_recent_actions(self, limit: int = 50) -> List[Dict]:
        """Get recent actions from the episodic log."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodic_log 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()
    
    def get_actions_since(self, timestamp: int) -> List[Dict]:
        """Get actions since a given timestamp."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM episodic_log 
                    WHERE timestamp >= ? 
                    ORDER BY timestamp ASC
                """, (timestamp,))
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()
    
    def clear_old_actions(self, keep_hours: int = 24):
        """Remove actions older than keep_hours."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cutoff = int(time.time()) - (keep_hours * 3600)
                cursor.execute("DELETE FROM episodic_log WHERE timestamp < ?", (cutoff,))
                deleted = cursor.rowcount
                conn.commit()
                return deleted
            finally:
                conn.close()

    # ==================== Model State (Phase 3) ====================

    def save_model_state(self, active_model: str, swap_count: int = 0):
        """Save current model state."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now = int(time.time())
                cursor.execute("""
                    INSERT OR REPLACE INTO model_state (id, active_model, loaded_at, last_swap_at, swap_count)
                    VALUES (1, ?, ?, ?, ?)
                """, (active_model, now, now, swap_count))
                conn.commit()
            finally:
                conn.close()

    def get_model_state(self) -> dict:
        """Get current model state."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM model_state WHERE id = 1")
                row = cursor.fetchone()
                if row is None:
                    return {"active_model": "primary", "loaded_at": 0, "last_swap_at": 0, "swap_count": 0}
                return dict(row)
            finally:
                conn.close()

    def update_model_swap(self, active_model: str, swap_count: int):
        """Update model swap tracking."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                now = int(time.time())
                cursor.execute("""
                    UPDATE model_state
                    SET active_model = ?, last_swap_at = ?, swap_count = ?
                    WHERE id = 1
                """, (active_model, now, swap_count))
                conn.commit()
            finally:
                conn.close()

    # ==================== Checkpoints (Phase 6) ====================

    def get_checkpoints(self, limit: int = 10) -> List[Dict]:
        """Get recent checkpoints."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM checkpoints
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict]:
        """Get a specific checkpoint."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM checkpoints WHERE id = ?
                """, (checkpoint_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM checkpoints WHERE id = ?
                """, (checkpoint_id,))
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
            finally:
                conn.close()

    def execute(self, sql: str, params: tuple = None):
        """Execute arbitrary SQL (for schema extensions)."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                conn.commit()
            finally:
                conn.close()


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
        _state_store = None
