"""
File context management — thin wrapper over MemoryManager.
All file state lives in core.memory.memory singleton.
"""
import re
import os
from pathlib import Path
from utils.logger import success, warning, info
from core.memory import memory as _mem

_loaded_files = {}  # kept for backward compat — mirrors _mem._files

def load_file(path):
    """Load a single file into memory."""
    p = Path(path).expanduser()
    if not p.exists():
        p = Path(os.getcwd()) / path
    if not p.exists():
        warning(f"File not found: {path}")
        return f"[ERROR] File not found: {path}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        key = str(p.resolve())
        _loaded_files[key] = content
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
        and not any(part.startswith(".") for part in f.parts)
        and "__pycache__" not in str(f)
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
    key = str(p)
    if key in _loaded_files:
        del _loaded_files[key]
    _mem.unload_file(str(p))
    info(f"Unloaded: {p.name}")

def clear_context():
    _loaded_files.clear()
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

def auto_load_from_prompt(prompt):
    found = detect_filenames(prompt)
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
