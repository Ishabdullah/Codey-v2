"""
File context management — thin wrapper over MemoryManager.
All file state lives in core.memory.memory singleton.
"""
import re
import os
import fnmatch
from pathlib import Path
from utils.logger import success, warning, info
from core.memory_v2 import memory as _mem

_DEFAULT_IGNORE = frozenset({
    ".env", "*.pem", "*.key", ".git", "__pycache__",
    ".pytest_cache", ".codey_sessions", "node_modules", ".venv"
})

# Cache: { cwd_str: (mtime_or_None, frozenset_of_patterns) }
_ignore_cache: dict = {}

def _load_ignore_patterns(cwd: str) -> frozenset:
    """Load and cache .codeyignore patterns for a given cwd."""
    ignore_file = Path(cwd) / ".codeyignore"
    mtime = ignore_file.stat().st_mtime if ignore_file.exists() else None
    cached = _ignore_cache.get(cwd)
    if cached and cached[0] == mtime:
        return cached[1]
    patterns = set(_DEFAULT_IGNORE)
    if ignore_file.exists():
        try:
            for line in ignore_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.add(line)
        except Exception:
            pass
    result = frozenset(patterns)
    _ignore_cache[cwd] = (mtime, result)
    return result

def is_ignored(path):
    """Check if a file should be ignored based on .codeyignore or defaults."""
    p = Path(path).expanduser().resolve()
    ignore_patterns = _load_ignore_patterns(os.getcwd())
            
    # Check filename and relative path
    name = p.name
    try:
        rel_path = str(p.relative_to(os.getcwd()))
    except ValueError:
        rel_path = str(p)

    for pat in ignore_patterns:
        # Normalize pattern
        p_pat = pat.rstrip("/")
        if fnmatch.fnmatch(name, p_pat) or fnmatch.fnmatch(rel_path, p_pat) or fnmatch.fnmatch(rel_path, pat):
            return True
        # Check if any part of the path matches
        for part in p.parts:
            if fnmatch.fnmatch(part, p_pat):
                return True
            
    return False

def load_file(path):
    """Load a single file into memory."""
    if is_ignored(path):
        warning(f"Ignored: {path}")
        return f"[ERROR] File is ignored by .codeyignore: {path}"

    p = Path(path).expanduser()
    if not p.exists():
        p = Path(os.getcwd()) / path
    if not p.exists():
        warning(f"File not found: {path}")
        return f"[ERROR] File not found: {path}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        _mem.load_file(str(p), content)
        success(f"Loaded: {p.name} ({len(content)} chars)")
        return content
    except Exception as e:
        return f"[ERROR] {e}"

def load_glob(pattern):
    import glob
    matches = glob.glob(pattern, recursive=True)
    if not matches:
        warning(f"No files matched: {pattern}")
        return []
    loaded = []
    for m in matches:
        p = Path(m)
        if p.is_file():
            r = load_file(str(p))
            if not r.startswith("[ERROR]"):
                loaded.append(str(p))
    if loaded:
        info(f"Loaded {len(loaded)} files matching '{pattern}'")
    return loaded

def load_directory(path, extensions=None, max_files=10):
    default_exts = {".py",".js",".ts",".sh",".md",".json",
                    ".yaml",".yml",".toml",".txt",".html",".css",
                    ".c",".cpp",".h",".rs",".go"}
    exts = set(extensions) if extensions else default_exts
    p = Path(path).expanduser()
    if not p.is_dir():
        warning(f"Not a directory: {path}")
        return []
    files = sorted([
        f for f in p.rglob("*")
        if f.is_file()
        and f.suffix in exts
        and not is_ignored(f)
    ])[:max_files]
    loaded = []
    for f in files:
        r = load_file(str(f))
        if not r.startswith("[ERROR]"):
            loaded.append(str(f))
    if loaded:
        info(f"Loaded {len(loaded)} files from {path}")
    return loaded

def unload_file(path):
    p = Path(path).expanduser().resolve()
    _mem.unload_file(str(p))
    info(f"Unloaded: {p.name}")

def clear_context():
    _mem.clear()
    info("File context cleared.")

def list_loaded():
    return list(_mem.list_files())

def build_file_context_block(message=""):
    return _mem.build_file_block(message)

def detect_filenames(text):
    pattern = r'(?:\.{0,2}/)?[\w\-/]+\.(?:py|js|ts|sh|json|yaml|yml|toml|txt|md|html|css|cpp|c|h|rs|go|rb|java)'
    matches = re.findall(pattern, text)
    existing = []
    for m in matches:
        p = Path(m).expanduser()
        if p.exists():
            existing.append(m)
        else:
            p2 = Path(os.getcwd()) / m
            if p2.exists():
                existing.append(str(p2))
    return existing

_SELF_REVIEW_KEYWORDS = [
    "review yourself", "review codey", "audit yourself", "audit codey",
    "analyze yourself", "analyse yourself", "analyze codey", "analyse codey",
    "review your own", "examine yourself", "assess yourself",
    "review your code", "your codebase", "your source",
]

_SELF_REVIEW_FILES = [
    "core/agent.py",
    "utils/config.py",
    "core/memory_v2.py",
    "tools/file_tools.py",
    "prompts/system_prompt.py",
]

def auto_load_from_prompt(prompt):
    found = detect_filenames(prompt)

    # Detect self-review requests and pre-load core files
    prompt_lower = prompt.lower()
    if any(kw in prompt_lower for kw in _SELF_REVIEW_KEYWORDS):
        for f in _SELF_REVIEW_FILES:
            if f not in found:
                found.append(f)

    loaded = []
    for f in found:
        from pathlib import Path as _P
        import os as _os
        key = str(_P(f).expanduser().resolve())
        if key in _mem._files:
            _mem.touch_file(f)
            continue  # already loaded, just touch it
        r = load_file(f)
        if not r.startswith("[ERROR]"):
            loaded.append(f)
    return loaded
