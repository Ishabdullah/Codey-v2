"""
File tools with confirmation + automatic history snapshots before writes.
"""
from pathlib import Path
from utils.file_utils import read_file, write_file, append_file, list_dir
from utils.logger import confirm as ask_confirm, warning, success
from utils.config import AGENT_CONFIG
from core.filehistory import snapshot

def tool_read_file(path: str) -> str:
    return read_file(path)


PROTECTED_FILES = {
    "main.py", "agent.py", "inference.py", "loader.py", "config.py",
    "system_prompt.py", "file_tools.py", "patch_tools.py", "shell_tools.py",
    "logger.py", "orchestrator.py", "taskqueue.py", "display.py",
    "memory.py", "context.py", "sessions.py", "tdd.py", "planner.py",
}

def _is_protected(path):
    from pathlib import Path as _P
    import os as _os
    fname = _P(path).name
    codey_dir = _P(__file__).parent.parent.resolve()
    target = _P(path).expanduser().resolve()
    try:
        target.relative_to(codey_dir)
        in_codey = True
    except ValueError:
        in_codey = False
    return in_codey and fname in PROTECTED_FILES

def tool_write_file(path: str, content: str) -> str:
    # Fix escaped quotes from model JSON confusion
    if content and '\\"' in content:
        content = content.replace('\\"', '"').replace("\\'", "'")
    if _is_protected(path):
        return f"[BLOCKED] {path} is a protected Codey source file and cannot be modified by agents."
    # Snapshot before overwriting
    snapshot(path)

    if AGENT_CONFIG["confirm_write"]:
        preview = content[:200] + ("..." if len(content) > 200 else "")
        warning(f"About to write to: {path}")
        print(f"Preview:\n{preview}")
        if not ask_confirm("Confirm write?"):
            return "[CANCELLED] Write cancelled by user."
    return write_file(path, content)

def tool_append_file(path: str, content: str) -> str:
    # Snapshot before appending
    snapshot(path)

    if AGENT_CONFIG["confirm_write"]:
        if not ask_confirm(f"Append to {path}?"):
            return "[CANCELLED] Append cancelled by user."
    return append_file(path, content)

def tool_list_dir(path: str = ".") -> str:
    return list_dir(path)
