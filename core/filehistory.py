"""
File history — stores backups of files before Codey writes them.
Powers /undo and /diff commands.
"""
import os
import shutil
from pathlib import Path
from datetime import datetime
from utils.logger import success, warning, info

# In-memory history: path -> list of (timestamp, content) tuples
# Most recent last.  Reduced from 5 to 2 — on a phone, 5 full copies
# of a 500-line file is ~50KB that never gets freed.  /undo only needs
# the last 1-2 versions in practice.
_history: dict[str, list[tuple[str, str]]] = {}
MAX_VERSIONS = 2

def snapshot(path: str) -> bool:
    """
    Save current contents of a file before it gets overwritten.
    Call this BEFORE writing. Returns True if snapshot was saved.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return False
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        key = str(p.resolve())
        if key not in _history:
            _history[key] = []
        timestamp = datetime.now().strftime("%H:%M:%S")
        _history[key].append((timestamp, content))
        # Keep only last MAX_VERSIONS
        if len(_history[key]) > MAX_VERSIONS:
            _history[key] = _history[key][-MAX_VERSIONS:]
        return True
    except Exception as e:
        warning(f"Could not snapshot {path}: {e}")
        return False

def get_versions(path: str) -> list[tuple[str, str]]:
    """Return list of (timestamp, content) for a file, oldest first."""
    p = Path(path).expanduser().resolve()
    return _history.get(str(p), [])

def undo(path: str) -> str:
    """
    Restore the previous version of a file.
    Returns status message.
    """
    p = Path(path).expanduser().resolve()
    key = str(p)
    versions = _history.get(key, [])

    if not versions:
        return f"[ERROR] No history for {path}. Was it edited this session?"

    timestamp, content = versions[-1]  # peek, don't pop yet
    try:
        # Snapshot current state before restoring (so /diff works after /undo)
        current = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
        p.write_text(content, encoding="utf-8")
        versions.pop()  # remove the restored version
        # Add current (pre-undo) as new snapshot so you can diff/redo
        undo_ts = datetime.now().strftime("%H:%M:%S") + " (pre-undo)"
        versions.append((undo_ts, current))
        remaining = len(versions)
        msg = f"Restored {path} to version from {timestamp}"
        if remaining > 0:
            msg += f" ({remaining} older version{'s' if remaining>1 else ''} available)"
        success(msg)
        return msg
    except Exception as e:
        # Put it back if write failed
        versions.append((timestamp, content))
        return f"[ERROR] Could not restore {path}: {e}"

def diff(path: str) -> str:
    """
    Show unified diff between last backup and current file.
    """
    import difflib
    p = Path(path).expanduser().resolve()
    key = str(p)
    versions = _history.get(key, [])

    if not versions:
        return f"No history for {path} — not edited this session."

    timestamp, old_content = versions[-1]
    try:
        new_content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[ERROR] Could not read current {path}: {e}"

    if old_content == new_content:
        return f"No changes in {path} since {timestamp}."

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"{path} (before, {timestamp})",
        tofile=f"{path} (current)",
        lineterm=""
    ))

    if not diff_lines:
        return f"No differences found in {path}."

    return "\n".join(diff_lines)

def list_history() -> dict[str, list[str]]:
    """Return dict of path -> list of timestamps for all tracked files."""
    return {
        path: [ts for ts, _ in versions]
        for path, versions in _history.items()
        if versions
    }

def clear_history():
    """Clear all file history."""
    _history.clear()
