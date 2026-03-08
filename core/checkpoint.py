#!/usr/bin/env python3
"""
Checkpoint system for Codey v2 self-modification.

Before modifying core files, creates a checkpoint:
- Git commit with checkpoint message
- Full file backup in ~/.codey-v2/checkpoints/
- SQLite record for tracking

Supports rollback to any checkpoint.
"""

import os
import shutil
import time
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from utils.logger import info, warning, error, success
from utils.config import CODE_DIR, CODEY_DIR
from core.state import get_state_store


# Checkpoint directory
CHECKPOINT_DIR = Path.home() / ".codey-v2" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

# Core files that should be checkpointed before modification
CORE_PATTERNS = [
    "core/*.py",
    "tools/*.py",
    "utils/*.py",
    "prompts/*.py",
]


@dataclass
class Checkpoint:
    """Represents a checkpoint."""
    id: str
    created_at: int
    reason: str
    files_modified: List[str]
    git_commit_hash: Optional[str]


def is_core_file(file_path: str) -> bool:
    """Check if a file is a core Codey file that needs checkpointing."""
    path = Path(file_path).resolve()
    
    # Check if in CODE_DIR (Codey source)
    try:
        path.relative_to(CODE_DIR)
        return True
    except ValueError:
        pass
    
    # Check patterns
    for pattern in CORE_PATTERNS:
        if path.match(pattern):
            return True
    
    return False


def create_checkpoint(reason: str, files_modified: List[str] = None) -> str:
    """
    Create a checkpoint before self-modification.
    
    Args:
        reason: Reason for checkpoint (e.g., "Adding new feature")
        files_modified: List of files that will be modified
        
    Returns:
        Checkpoint ID (timestamp)
    """
    checkpoint_id = str(int(time.time()))
    backup_dir = CHECKPOINT_DIR / checkpoint_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    info(f"Checkpoint: creating '{checkpoint_id}' - {reason}")
    
    # Backup core files
    backed_up = []
    
    # Backup all Python files in core directories
    for pattern in CORE_PATTERNS:
        base_path = CODE_DIR / pattern.split('/')[0]
        if base_path.exists():
            for py_file in base_path.rglob("*.py"):
                try:
                    rel_path = py_file.relative_to(CODE_DIR)
                    dest = backup_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(py_file, dest)
                    backed_up.append(str(rel_path))
                except Exception as e:
                    warning(f"Checkpoint: could not backup {py_file}: {e}")
    
    # Also backup specific important files
    important_files = [
        CODE_DIR / "main.py",
        CODE_DIR / "codey",
        CODE_DIR / "codey2",
    ]
    for f in important_files:
        if f.exists():
            try:
                dest = backup_dir / f.name
                shutil.copy2(f, dest)
                backed_up.append(f.name)
            except Exception as e:
                warning(f"Checkpoint: could not backup {f}: {e}")
    
    # Create git commit
    git_hash = _create_git_commit(reason)
    
    # Record in database
    state = get_state_store()
    state.execute("""
        INSERT INTO checkpoints (id, created_at, reason, files_modified, git_commit_hash)
        VALUES (?, ?, ?, ?, ?)
    """, (checkpoint_id, int(time.time()), reason, json.dumps(files_modified or []), git_hash))
    
    success(f"Checkpoint '{checkpoint_id}' created ({len(backed_up)} files backed up)")
    
    return checkpoint_id


def _create_git_commit(reason: str) -> Optional[str]:
    """Create a git commit for the checkpoint."""
    try:
        # Check if we're in a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=CODE_DIR,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return None
        
        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=CODE_DIR,
            capture_output=True
        )
        
        # Check if there are changes to commit
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=CODE_DIR,
            capture_output=True
        )
        if result.returncode == 0:
            # No changes
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=CODE_DIR,
                capture_output=True,
                text=True
            )
            return result.stdout.strip() if result.returncode == 0 else None
        
        # Create commit
        subprocess.run(
            ["git", "commit", "-m", f"Codey checkpoint: {reason}"],
            cwd=CODE_DIR,
            capture_output=True
        )
        
        # Get commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=CODE_DIR,
            capture_output=True,
            text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None
        
    except Exception as e:
        warning(f"Checkpoint: git commit failed: {e}")
        return None


def rollback(checkpoint_id: str) -> bool:
    """
    Rollback to a checkpoint.
    
    Args:
        checkpoint_id: Checkpoint ID to rollback to
        
    Returns:
        True if rollback successful
    """
    backup_dir = CHECKPOINT_DIR / checkpoint_id
    
    if not backup_dir.exists():
        error(f"Rollback: checkpoint '{checkpoint_id}' not found")
        return False
    
    info(f"Rollback: restoring from '{checkpoint_id}'")
    
    # Restore files from backup
    restored = 0
    for backup_file in backup_dir.rglob("*"):
        if backup_file.is_file():
            try:
                rel_path = backup_file.relative_to(backup_dir)
                dest = CODE_DIR / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, dest)
                restored += 1
            except Exception as e:
                error(f"Rollback: could not restore {backup_file}: {e}")
    
    # Try to git checkout the commit
    state = get_state_store()
    checkpoint_data = state.get_checkpoint(checkpoint_id)
    
    if checkpoint_data and checkpoint_data.get("git_commit_hash"):
        git_hash = checkpoint_data["git_commit_hash"]
        try:
            subprocess.run(
                ["git", "checkout", git_hash],
                cwd=CODE_DIR,
                capture_output=True
            )
            info(f"Rollback: checked out git commit {git_hash[:8]}")
        except Exception as e:
            warning(f"Rollback: git checkout failed: {e}")
    
    success(f"Rollback: restored {restored} files from checkpoint '{checkpoint_id}'")
    
    # Log in episodic memory
    state.log_action("rollback", f"Restored from checkpoint {checkpoint_id}")
    
    return True


def list_checkpoints(limit: int = 10) -> List[Dict]:
    """
    List recent checkpoints.
    
    Args:
        limit: Maximum number of checkpoints to return
        
    Returns:
        List of checkpoint info dicts
    """
    state = get_state_store()
    checkpoints = state.get_checkpoints(limit)
    
    result = []
    for cp in checkpoints:
        result.append({
            "id": cp["id"],
            "created_at": cp["created_at"],
            "reason": cp["reason"],
            "git_commit": cp["git_commit_hash"][:8] if cp["git_commit_hash"] else None,
        })
    
    return result


def get_latest_checkpoint() -> Optional[str]:
    """Get the most recent checkpoint ID."""
    state = get_state_store()
    checkpoints = state.get_checkpoints(1)
    return checkpoints[0]["id"] if checkpoints else None


def prune_checkpoints(keep_count: int = 5):
    """
    Remove old checkpoints, keeping only the most recent ones.
    
    Args:
        keep_count: Number of recent checkpoints to keep
    """
    state = get_state_store()
    checkpoints = state.get_checkpoints(100)  # Get all
    
    if len(checkpoints) <= keep_count:
        return
    
    to_remove = checkpoints[keep_count:]
    
    for cp in to_remove:
        checkpoint_id = cp["id"]
        backup_dir = CHECKPOINT_DIR / checkpoint_id
        
        # Remove backup directory
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        
        # Remove from database
        state.delete_checkpoint(checkpoint_id)
        
        info(f"Checkpoint: pruned '{checkpoint_id}'")
    
    success(f"Checkpoint: pruned {len(to_remove)} old checkpoints")


# State store extensions for checkpoints
def _extend_state_schema():
    """Add checkpoints table to state schema."""
    state = get_state_store()
    state.execute("""
        CREATE TABLE IF NOT EXISTS checkpoints (
            id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            reason TEXT NOT NULL,
            files_modified TEXT,
            git_commit_hash TEXT
        )
    """)


# Initialize on import
_extend_state_schema()
