"""
Project context detection.
Auto-detects project type and key files when cwd changes.
"""
import os
import json
from pathlib import Path
from utils.logger import info, success

# Signatures to detect project type
PROJECT_SIGNATURES = {
    "python":     ["requirements.txt", "setup.py", "pyproject.toml", "*.py"],
    "node":       ["package.json", "node_modules"],
    "rust":       ["Cargo.toml"],
    "go":         ["go.mod"],
    "shell":      ["*.sh"],
    "web":        ["index.html", "*.html"],
    "c/cpp":      ["Makefile", "CMakeLists.txt", "*.c", "*.cpp"],
}

# Files worth reading for context (small config/manifest files)
CONTEXT_FILES = [
    "README.md", "readme.md", "README.txt",
    "requirements.txt", "package.json",
    "Cargo.toml", "go.mod", "pyproject.toml",
    ".env.example",
]

_project_cache: dict = {}
_last_cwd: str = ""

def get_repo_map(cwd: str = None) -> str:
    """Generate a lightweight map of the project (symbols, classes, imports)."""
    from core.context import is_ignored
    cwd = Path(cwd or os.getcwd())
    
    # Only scan these extensions
    map_exts = {".py", ".js", ".ts", ".c", ".cpp", ".rs", ".go"}
    
    # Heuristic for symbols
    patterns = [
        r"^class\s+(\w+)",
        r"^def\s+(\w+)",
        r"^function\s+(\w+)",
        r"^async\s+def\s+(\w+)",
        r"^export\s+(?:async\s+)?(?:function|class)\s+(\w+)",
        r"^(?:import|from)\s+[\w.]+",
    ]
    import re
    
    repo_map = []
    
    # Limit to first 50 relevant files to keep it fast
    try:
        files = sorted([
            f for f in cwd.rglob("*")
            if f.is_file()
            and f.suffix in map_exts
            and not is_ignored(f)
        ])[:50]
    except Exception:
        return ""
        
    for f in files:
        rel = f.relative_to(cwd)
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            symbols = []
            for line in content.splitlines():
                line = line.strip()
                if any(re.search(p, line) for p in patterns):
                    # Clean up the line for the map
                    symbols.append(line[:80])
            if symbols:
                repo_map.append(f"📄 {rel}:\n  " + "\n  ".join(symbols[:15]))
        except Exception:
            continue
            
    if not repo_map:
        return ""
        
    return "## Project Map\n" + "\n\n".join(repo_map)

def detect_project(cwd: str = None) -> dict:
    """
    Detect project type and gather context from cwd.
    Returns a dict with: type, files, summary
    """
    global _project_cache, _last_cwd

    cwd = cwd or os.getcwd()

    # Return cached result if cwd hasn't changed
    if cwd == _last_cwd and _project_cache:
        return _project_cache

    _last_cwd = cwd
    cwd_path = Path(cwd)

    result = {
        "cwd": cwd,
        "type": "unknown",
        "key_files": [],
        "context": "",
    }

    # Detect project type
    try:
        entries = set(p.name for p in cwd_path.iterdir())
    except Exception:
        return result

    for proj_type, signatures in PROJECT_SIGNATURES.items():
        for sig in signatures:
            if "*" in sig:
                ext = sig.replace("*", "")
                if any(e.endswith(ext) for e in entries):
                    result["type"] = proj_type
                    break
            elif sig in entries:
                result["type"] = proj_type
                break
        if result["type"] != "unknown":
            break

    # Find key files that exist
    result["key_files"] = [f for f in CONTEXT_FILES if (cwd_path / f).exists()]

    # Build context string from key files
    context_parts = [f"Project type: {result['type']}", f"Directory: {cwd}"]

    # List top-level files (limit to 20)
    try:
        top_files = sorted(
            [p.name for p in cwd_path.iterdir() if not p.name.startswith(".")],
            key=lambda x: (Path(x).suffix, x)
        )[:20]
        context_parts.append(f"Files: {', '.join(top_files)}")
    except Exception:
        pass

    # Read small key files for context
    for fname in result["key_files"]:
        fpath = cwd_path / fname
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            # Only include if small enough
            if len(content) < 800:
                context_parts.append(f"\n{fname}:\n{content.strip()}")
            else:
                context_parts.append(f"\n{fname}: (exists, {len(content)} chars)")
        except Exception:
            pass

    result["context"] = "\n".join(context_parts)
    _project_cache = result
    return result

def get_project_summary() -> str:
    """Get a compact project summary for injection into system prompt."""
    proj = detect_project()
    if proj["type"] == "unknown" and not proj["key_files"]:
        return ""
    return proj["context"]

def invalidate_cache():
    """Call this when cwd changes."""
    global _project_cache, _last_cwd
    _project_cache = {}
    _last_cwd = ""
