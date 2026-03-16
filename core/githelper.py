"""
Git helper for Codey-v2.

v2.5.5 — Phase 3: branch management, smart commit messages,
                   merge conflict detection and resolution.
"""
import subprocess
import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from utils.logger import success, error, info, warning


# ── Basic repo queries ─────────────────────────────────────────────────────────

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


def git_log(n: int = 5, path: str = None) -> str:
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "log", f"-{n}", "--oneline"],
        capture_output=True, text=True, cwd=path
    )
    return result.stdout.strip() or "No commits yet."


def git_current_branch(path: str = None) -> str:
    """Return the name of the current branch."""
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=path
    )
    return result.stdout.strip() or "unknown"


# ── Commit ─────────────────────────────────────────────────────────────────────

def git_commit(message: str, path: str = None, add_all: bool = True) -> str:
    path = path or os.getcwd()

    if not is_git_repo(path):
        return "[ERROR] Not a git repository."

    if add_all:
        result = subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, text=True, cwd=path
        )
        if result.returncode != 0:
            return f"[ERROR] git add failed: {result.stderr}"

    status = git_status(path)
    if status == "Nothing to commit.":
        return "Nothing to commit — working tree clean."

    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True, text=True, cwd=path
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return f"[ERROR] {result.stderr.strip()}"


def git_push(path: str = None) -> str:
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "push"],
        capture_output=True, text=True, cwd=path
    )
    if result.returncode == 0:
        return result.stdout.strip() or "Pushed successfully."
    return f"[ERROR] {result.stderr.strip()}"


# ── Branch management (Phase 3.1) ─────────────────────────────────────────────

def git_branches(path: str = None) -> str:
    """
    List all local branches with current branch marked.
    Shows remote-tracking refs too when present.
    """
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "branch", "-a", "--format=%(HEAD) %(refname:short)"],
        capture_output=True, text=True, cwd=path
    )
    if result.returncode != 0 or not result.stdout.strip():
        return "No branches found."

    lines = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("* "):
            lines.append(f"[bold green]* {line[2:]}[/bold green]  (current)")
        else:
            lines.append(f"  {line}")
    return "\n".join(lines)


def git_branch_create(name: str, path: str = None) -> str:
    """Create a new branch and switch to it immediately."""
    path = path or os.getcwd()
    # Validate name (no spaces, no special chars)
    if re.search(r"[\s~^:?*\[\\\]@{]", name):
        return f"[ERROR] Invalid branch name: '{name}'"

    result = subprocess.run(
        ["git", "checkout", "-b", name],
        capture_output=True, text=True, cwd=path
    )
    if result.returncode == 0:
        return f"Created and switched to branch '{name}'."
    return f"[ERROR] {result.stderr.strip()}"


def git_checkout(name: str, path: str = None) -> str:
    """Switch to an existing branch."""
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "checkout", name],
        capture_output=True, text=True, cwd=path
    )
    if result.returncode == 0:
        msg = result.stderr.strip() or result.stdout.strip()
        return msg or f"Switched to branch '{name}'."
    return f"[ERROR] {result.stderr.strip()}"


def git_merge(branch: str, path: str = None) -> str:
    """
    Merge `branch` into the current branch.

    Returns:
        "OK: <output>"              on clean merge
        "[CONFLICT] <output>"       when conflict markers were written
        "[ERROR] <message>"         on other failure
    """
    path = path or os.getcwd()
    result = subprocess.run(
        ["git", "merge", branch],
        capture_output=True, text=True, cwd=path
    )
    combined = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        return f"OK: {combined or 'Merged successfully.'}"
    if "CONFLICT" in combined.upper():
        return f"[CONFLICT] {combined}"
    return f"[ERROR] {combined}"


# ── Conflict detection & parsing (Phase 3.2) ──────────────────────────────────

def detect_conflicts(path: str = None) -> List[str]:
    """
    Return a list of files that currently have merge conflict markers
    in the working tree.  Uses 'git diff --name-only --diff-filter=U'
    which is the authoritative way to find unmerged paths.
    """
    cwd = path or os.getcwd()
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        capture_output=True, text=True, cwd=cwd
    )
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    # Fallback: grep for conflict markers (catches edge cases)
    if not files:
        result2 = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, cwd=cwd
        )
        for line in result2.stdout.splitlines():
            if line.startswith("UU ") or line.startswith("AA "):
                files.append(line[3:].strip())
    return files


def get_conflict_sections(filepath: str) -> dict:
    """
    Parse a file containing git conflict markers and extract both sides.

    Returns a dict:
        {
            "has_conflicts": bool,
            "ours":   str,   # HEAD / current branch content
            "theirs": str,   # Incoming branch content
            "pre":    str,   # Lines before first conflict
            "post":   str,   # Lines after last conflict
            "raw":    str,   # Full file content
            "count":  int,   # Number of conflict blocks
        }
    """
    try:
        raw = Path(filepath).read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"has_conflicts": False, "error": str(e)}

    if "<<<<<<< " not in raw:
        return {"has_conflicts": False, "raw": raw, "count": 0}

    ours_blocks: List[str] = []
    theirs_blocks: List[str] = []
    pre_lines: List[str] = []
    post_lines: List[str] = []

    state = "pre"   # pre | ours | theirs | post
    ours_buf: List[str] = []
    theirs_buf: List[str] = []

    for line in raw.splitlines(keepends=True):
        if line.startswith("<<<<<<<"):
            state = "ours"
            ours_buf = []
        elif line.startswith("=======") and state == "ours":
            state = "theirs"
            theirs_buf = []
        elif line.startswith(">>>>>>>") and state == "theirs":
            ours_blocks.append("".join(ours_buf))
            theirs_blocks.append("".join(theirs_buf))
            state = "post"
        elif state == "pre":
            pre_lines.append(line)
        elif state == "ours":
            ours_buf.append(line)
        elif state == "theirs":
            theirs_buf.append(line)
        elif state == "post":
            post_lines.append(line)

    return {
        "has_conflicts": True,
        "ours":   "\n---\n".join(ours_blocks),
        "theirs": "\n---\n".join(theirs_blocks),
        "pre":    "".join(pre_lines),
        "post":   "".join(post_lines),
        "raw":    raw,
        "count":  len(ours_blocks),
    }


# ── Smart commit helpers (Phase 3.3) ──────────────────────────────────────────

def git_diff_for_commit(path: str = None, max_chars: int = 3000) -> str:
    """
    Get a diff suitable for generating a commit message.
    Tries staged diff first, then unstaged.
    Truncates to `max_chars` to stay within context window.
    """
    cwd = path or os.getcwd()

    for args in (["git", "diff", "--cached"], ["git", "diff"]):
        result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
        if result.stdout.strip():
            diff = result.stdout.strip()
            if len(diff) > max_chars:
                diff = diff[:max_chars] + "\n... (truncated)"
            return diff

    # Nothing staged or unstaged — use HEAD diff
    result = subprocess.run(
        ["git", "diff", "HEAD~1", "HEAD"],
        capture_output=True, text=True, cwd=cwd
    )
    diff = result.stdout.strip()
    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n... (truncated)"
    return diff or "(no diff available)"


def git_commit_log_messages(n: int = 10, path: str = None) -> List[str]:
    """Return the last n commit subject lines (for style detection)."""
    cwd = path or os.getcwd()
    result = subprocess.run(
        ["git", "log", f"-{n}", "--format=%s"],
        capture_output=True, text=True, cwd=cwd
    )
    return [l.strip() for l in result.stdout.splitlines() if l.strip()]


def uses_conventional_commits(messages: List[str]) -> bool:
    """
    Return True if the majority of recent commits follow conventional commits
    format:  type(scope)?: description
    """
    if not messages:
        return False
    _cc_re = re.compile(
        r"^(feat|fix|docs|style|refactor|test|chore|perf|ci|build|revert)"
        r"(\([^)]+\))?!?:\s+.+",
        re.IGNORECASE,
    )
    hits = sum(1 for m in messages if _cc_re.match(m))
    return hits >= max(1, len(messages) // 2)


def generate_commit_message(diff: str, history_msgs: List[str]) -> str:
    """
    Use the inference engine to generate a meaningful commit message
    from a git diff.  Calls infer() directly (no tool loop needed).

    Returns a single-line commit message string.
    """
    from core.inference_v2 import infer

    cc_style = uses_conventional_commits(history_msgs)
    style_hint = (
        "Use conventional commits format: type(scope)?: description\n"
        "Types: feat, fix, docs, style, refactor, test, chore, perf\n"
        "Examples: 'feat: add voice interface', 'fix: agent loop on simple writes'"
        if cc_style else
        "Write a clear, descriptive single-line message.\n"
        "Examples: 'Add voice TTS/STT interface', 'Fix agent loop after file write'"
    )

    prompt_text = (
        f"Git diff:\n```\n{diff}\n```\n\n"
        f"Task: Write ONE commit message line for this diff.\n"
        f"{style_hint}\n"
        "Reply with ONLY the commit message. No explanation. No quotes."
    )

    messages = [
        {"role": "system", "content": "You are a git commit message writer. Output only the commit message line, nothing else."},
        {"role": "user",   "content": prompt_text},
    ]

    try:
        result = infer(messages, stream=False, show_thinking=False)
        if result and not result.startswith("[ERROR]"):
            # Clean up: strip quotes, trim, take first line only
            msg = result.strip().strip('"\'`').splitlines()[0].strip()
            # Cap length
            return msg[:100] if len(msg) > 100 else msg
    except Exception:
        pass

    return "Update project files"
