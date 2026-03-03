"""
/git — stage and commit from inside Codey chat.
"""
import subprocess
import os
from pathlib import Path
from utils.logger import success, error, info, warning

def is_git_repo(path: str = None) -> bool:
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True, cwd=path
    )
    return result.returncode == 0

def git_status(path: str = None) -> str:
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "status", "--short"],
        capture_output=True, text=True, cwd=path
    )
    return result.stdout.strip() or "Nothing to commit."

def git_diff_stat(path: str = None) -> str:
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD"],
        capture_output=True, text=True, cwd=path
    )
    return result.stdout.strip()

def git_commit(message: str, path: str = None, add_all: bool = True) -> str:
    path = path or os.getcwd()

    if not is_git_repo(path):
        return "[ERROR] Not a git repository."

    # Stage all changes
    if add_all:
        result = subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, text=True, cwd=path
        )
        if result.returncode != 0:
            return f"[ERROR] git add failed: {result.stderr}"

    # Check there's something to commit
    status = git_status(path)
    if status == "Nothing to commit.":
        return "Nothing to commit — working tree clean."

    # Commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True, text=True, cwd=path
    )
    if result.returncode == 0:
        return result.stdout.strip()
    else:
        return f"[ERROR] {result.stderr.strip()}"

def git_push(path: str = None) -> str:
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "push"],
        capture_output=True, text=True, cwd=path
    )
    if result.returncode == 0:
        return result.stdout.strip() or "Pushed successfully."
    else:
        return f"[ERROR] {result.stderr.strip()}"

def git_log(n: int = 5, path: str = None) -> str:
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "log", f"-{n}", "--oneline"],
        capture_output=True, text=True, cwd=path
    )
    return result.stdout.strip() or "No commits yet."
