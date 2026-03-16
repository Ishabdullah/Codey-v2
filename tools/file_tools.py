#!/usr/bin/env python3
"""
File tools for Codey-v2.

Refactored for v2: Uses core/filesystem.Filesystem class for direct access.
Confirmation logic moved to agent layer. No more PROTECTED_FILES block.
Snapshots handled by Filesystem class.
"""

from pathlib import Path
from typing import List, Union
from core.filesystem import Filesystem, get_filesystem, FilesystemAccessError
from utils.config import AGENT_CONFIG

# Files that must never be silently overwritten — always prompt regardless of yolo.
# These are repo/project metadata files whose loss is hard to recover without git history.
WRITE_PROTECTED = {
    ".gitignore",
    "README.md", "readme.md",
    "CLAUDE.md", "CODEY.md",
    "requirements.txt", "requirements-dev.txt",
    "setup.py", "setup.cfg", "pyproject.toml",
    "Makefile",
    ".env",
}

# Global filesystem instance
_fs: Filesystem = None
_fs_allow_self_mod: bool = False


def _get_fs() -> Filesystem:
    """Get or create filesystem instance."""
    global _fs, _fs_allow_self_mod
    
    # Check if allow_self_modification setting changed
    allow_self_mod = AGENT_CONFIG.get("allow_self_modification", False)
    
    if _fs is None or _fs_allow_self_mod != allow_self_mod:
        _fs = get_filesystem(allow_self_modification=allow_self_mod)
        _fs_allow_self_mod = allow_self_mod
    
    return _fs


def tool_read_file(path: str) -> str:
    """
    Read file content.
    
    Args:
        path: Path to file
        
    Returns:
        File content or error message
    """
    try:
        return _get_fs().read(path)
    except FilesystemAccessError as e:
        return f"[ERROR] {e}"


def tool_write_file(path: str, content: str) -> str:
    """
    Write file content.

    - WRITE_PROTECTED files (e.g. .gitignore, README.md) always require
      explicit confirmation when the file already exists.
    - All other existing files require confirmation when AGENT_CONFIG
      confirm_write is True.

    Args:
        path: Path to file
        content: Content to write

    Returns:
        Success message or error message
    """
    from utils.logger import confirm as ask_confirm, warning as log_warning

    p = Path(path)
    if not p.is_absolute():
        import os
        p = Path(os.getcwd()) / path
    file_exists = p.exists() and p.is_file()

    # Protected files: always confirm before overwriting.
    if file_exists and p.name in WRITE_PROTECTED:
        log_warning(f"Attempting to overwrite protected file: {path}")
        if not ask_confirm(f"Really overwrite {p.name}?"):
            return f"[CANCELLED] Overwrite of {path} cancelled."

    # Regular files: confirm if the flag is set.
    elif file_exists and AGENT_CONFIG.get("confirm_write"):
        log_warning(f"About to overwrite: {path}")
        if not ask_confirm(f"Overwrite {path}?"):
            return f"[CANCELLED] Overwrite of {path} cancelled."

    try:
        return _get_fs().write(path, content)
    except FilesystemAccessError as e:
        return f"[ERROR] {e}"


def tool_patch_file(path: str, old_str: str, new_str: str) -> str:
    """
    Patch file content (replace old_str with new_str).
    
    Args:
        path: Path to file
        old_str: String to find and replace
        new_str: Replacement string
        
    Returns:
        Diff of changes or error message
    """
    try:
        return _get_fs().patch(path, old_str, new_str)
    except FilesystemAccessError as e:
        return f"[ERROR] {e}"


def tool_append_file(path: str, content: str) -> str:
    """
    Append content to file.
    
    Args:
        path: Path to file
        content: Content to append
        
    Returns:
        Success message or error message
    """
    try:
        return _get_fs().append(path, content)
    except FilesystemAccessError as e:
        return f"[ERROR] {e}"


def tool_list_dir(path: str = ".") -> str:
    """
    List directory contents.
    
    Args:
        path: Directory path (default: current directory)
        
    Returns:
        Formatted list of entries or error message
    """
    try:
        entries = _get_fs().list_dir(path)
        # Format as multi-line string
        lines = []
        for entry in entries:
            full_path = Path(path) / entry
            if full_path.is_dir():
                lines.append(f"📁 {entry}/")
            else:
                lines.append(f"📄 {entry}")
        return "\n".join(lines)
    except FilesystemAccessError as e:
        return f"[ERROR] {e}"


def file_exists(path: str) -> bool:
    """Check if file exists."""
    return _get_fs().exists(path)


def file_is_file(path: str) -> bool:
    """Check if path is a file."""
    return _get_fs().is_file(path)


def file_is_dir(path: str) -> bool:
    """Check if path is a directory."""
    return _get_fs().is_dir(path)
