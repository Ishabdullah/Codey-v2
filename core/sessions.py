"""
Session persistence — save and restore conversation history between sessions.
Sessions stored in ~/.codey_sessions/ as JSON files named by project path.
"""
import json
import re
import os
import hashlib
from pathlib import Path
from datetime import datetime
from utils.logger import success, info, warning

SESSIONS_DIR = Path.home() / ".codey_sessions"

# Each entry: (compiled pattern, replacement string)
# For key=value pairs use group \1 to keep the key, redact the value.
_SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{48}"),                    "[REDACTED]"),           # OpenAI key
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"),                   "[REDACTED]"),           # GitHub PAT
    (re.compile(r'("password"\s*:\s*)"[^"]+"'),             r'\1"[REDACTED]"'),      # JSON password
    (re.compile(r'(password\s*=\s*)\S+'),                   r'\1[REDACTED]'),        # env password
    (re.compile(r'(api[_-]key\s*[:=]\s*)[a-zA-Z0-9_\-]{20,}', re.I), r'\1[REDACTED]'), # generic key
]

def redact_secrets(text: str) -> str:
    """Mask potential secrets in text before saving to disk."""
    if not isinstance(text, str):
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text

def _session_path(project_dir: str = None) -> Path:
    """Get session file path for a project directory."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    cwd = project_dir or os.getcwd()
    # Hash the path to make a safe filename
    key = hashlib.sha256(cwd.encode()).hexdigest()[:12]
    # Also include last dir name for readability
    name = Path(cwd).name
    return SESSIONS_DIR / f"{name}_{key}.json"

def save_session(history: list, project_dir: str = None, max_turns: int = 6):
    """Save conversation history to disk. Keeps last max_turns turns."""
    if not history:
        return
    path = _session_path(project_dir)
    # Keep only recent history and redact secrets
    keep = history[-max_turns * 2:]
    safe_history = []
    for turn in keep:
        safe_turn = turn.copy()
        safe_turn["content"] = redact_secrets(turn["content"])
        safe_history.append(safe_turn)

    data = {
        "saved_at":  datetime.now().isoformat(),
        "project":   project_dir or os.getcwd(),
        "turns":     len(safe_history) // 2,
        "history":   safe_history,
    }
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        warning(f"Could not save session: {e}")

def load_session(project_dir: str = None, path: str = None) -> list:
    """Load conversation history from disk. Returns empty list if none."""
    if path:
        path = Path(path)
    else:
        path = _session_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        history = data.get("history", [])
        saved_at = data.get("saved_at", "unknown")[:16].replace("T", " ")
        turns = data.get("turns", len(history) // 2)
        info(f"Resumed session: {turns} turns from {saved_at}")
        return history
    except Exception as e:
        warning(f"Could not load session: {e}")
        return []

def clear_session(project_dir: str = None):
    """Delete saved session for current project."""
    path = _session_path(project_dir)
    if path.exists():
        path.unlink()
        success("Session cleared.")
    else:
        info("No saved session found.")

def list_sessions() -> list[dict]:
    """List all saved sessions."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text())
            sessions.append({
                "file":     f.name,
                "project":  data.get("project", "unknown"),
                "turns":    data.get("turns", 0),
                "saved_at": data.get("saved_at", "")[:16].replace("T", " "),
            })
        except Exception:
            pass
    return sessions

def session_exists(project_dir: str = None) -> bool:
    return _session_path(project_dir).exists()
