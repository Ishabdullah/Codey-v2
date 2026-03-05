"""
File tools with confirmation + automatic history snapshots before writes.
"""
from pathlib import Path
from utils.file_utils import read_file, write_file, append_file, list_dir
from utils.logger import confirm as ask_confirm, warning, success
from utils.config import AGENT_CONFIG, WORKSPACE_ROOT, CODE_DIR
from core.filehistory import snapshot

def is_outside_workspace(path: str) -> bool:
    p = Path(path).expanduser().resolve()
    try:
        p.relative_to(WORKSPACE_ROOT)
        return False
    except ValueError:
        # If not relative to workspace, it's outside
        # Check if it's relative to CODE_DIR (protected anyway)
        try:
            p.relative_to(CODE_DIR)
            return False
        except ValueError:
            return True

def tool_read_file(path: str) -> str:
    if is_outside_workspace(path):
        warning(f"Accessing file outside workspace: {path}")
        if not ask_confirm("Confirm read?"):
            return "[CANCELLED] Read outside workspace denied by user."
    return read_file(path)

PROTECTED_FILES = {
    "main.py", "agent.py", "inference.py", "loader.py", "config.py",
    "system_prompt.py", "file_tools.py", "patch_tools.py", "shell_tools.py",
    "logger.py", "orchestrator.py", "taskqueue.py", "display.py",
    "memory.py", "context.py", "sessions.py", "tdd.py", "planner.py",
}

def _is_protected(path):
    p = Path(path).expanduser().resolve()
    fname = p.name
    try:
        p.relative_to(CODE_DIR)
        return fname in PROTECTED_FILES
    except ValueError:
        return False

def tool_write_file(path: str, content: str) -> str:
    # Fix escaped quotes from model JSON confusion
    if content and '\\"' in content:
        content = content.replace('\\"', '"').replace("\\'", "'")
    
    if _is_protected(path):
        return f"[BLOCKED] {path} is a protected Codey source file."
        
    if is_outside_workspace(path):
        warning(f"Writing file outside workspace: {path}")
        if not ask_confirm("Confirm write outside workspace?"):
            return "[CANCELLED] Write outside workspace denied by user."

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
