"""
/search — grep across project files from inside Codey chat.
"""
import subprocess
import os
from pathlib import Path
from utils.logger import warning

DEFAULT_EXTENSIONS = [
    "*.py", "*.js", "*.ts", "*.sh", "*.json",
    "*.yaml", "*.yml", "*.toml", "*.md", "*.txt",
    "*.html", "*.css", "*.c", "*.cpp", "*.h", "*.rs", "*.go",
]

def search_in_project(pattern: str, path: str = ".", case_sensitive: bool = False) -> str:
    """
    Search for pattern across project files using grep.
    Returns formatted results string.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return f"[ERROR] Path not found: {path}"

    cmd = ["grep", "-rn"]
    for ext in DEFAULT_EXTENSIONS:
        cmd += ["--include", ext]
    if not case_sensitive:
        cmd.append("-i")
    cmd += ["--color=never", pattern, str(p)]

    # Exclude pycache and .git
    cmd += ["--exclude-dir=__pycache__", "--exclude-dir=.git",
            "--exclude-dir=node_modules", "--exclude-dir=.venv"]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            cwd=os.getcwd()
        )
        output = result.stdout.strip()
        if not output:
            return f"No matches for '{pattern}' in {path}"

        lines = output.splitlines()
        # Truncate if too many results
        if len(lines) > 50:
            shown = lines[:50]
            return "\n".join(shown) + f"\n... ({len(lines) - 50} more results)"
        return output

    except subprocess.TimeoutExpired:
        return "[ERROR] Search timed out"
    except FileNotFoundError:
        return "[ERROR] grep not found"
    except Exception as e:
        return f"[ERROR] {e}"

def search_definitions(name: str, path: str = ".") -> str:
    """Search for function/class definitions by name."""
    patterns = [f"def {name}", f"class {name}", f"function {name}", f"const {name}"]
    results = []
    for pat in patterns:
        r = search_in_project(pat, path, case_sensitive=True)
        if not r.startswith("No matches") and not r.startswith("[ERROR]"):
            results.append(r)
    return "\n".join(results) if results else f"No definition found for '{name}'"
