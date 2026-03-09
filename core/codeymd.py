import os
from pathlib import Path
from utils.logger import success, info

CODEYMD_FILENAME = "CODEY.md"
_codeymd_cache: dict = {}  # tracks which paths we've already logged

def find_codeymd(start: str = None) -> Path | None:
    start = Path(start or os.getcwd())
    for directory in [start] + list(start.parents)[:2]:
        candidate = directory / CODEYMD_FILENAME
        if candidate.exists():
            return candidate
    return None

def read_codeymd(start: str = None) -> str:
    path = find_codeymd(start)
    if not path:
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
        if "Write a concise CODEY.md" in content or "Analyze this project" in content:
            return ""
        if str(path) not in _codeymd_cache:
            success(f"Loaded CODEY.md from {path}")
            _codeymd_cache[str(path)] = True
        return content
    except Exception:
        return ""

def write_codeymd(content: str, directory: str = None) -> str:
    directory = Path(directory or os.getcwd())
    path = directory / CODEYMD_FILENAME
    try:
        path.write_text(content, encoding="utf-8")
        return str(path)
    except Exception as e:
        return f"[ERROR] {e}"

def get_init_prompt(project_info: dict) -> str:
    files = project_info.get('context', '')
    return f"""Write a CODEY.md file for this project. Output ONLY the markdown content, nothing else.

Project details:
{files}

Use exactly these sections (skip any that don't apply):

# Project
One sentence: what does this project do?

# Stack
Languages and key libraries.

# Structure
Key directories and what they contain.

# Commands
How to run, test, build.

# Conventions
Code style or architecture rules to follow.

# Notes
Anything important an AI assistant should know.

Write the CODEY.md now. Output only markdown, no explanation, no preamble."""
