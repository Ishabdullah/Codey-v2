"""
patch_file — surgical find/replace in files.
Much more efficient than write_file for small edits.
"""
from pathlib import Path
from utils.logger import confirm as ask_confirm, warning, success
from utils.config import AGENT_CONFIG
from core.filehistory import snapshot

def tool_patch_file(path: str, old_str: str, new_str: str) -> str:
    """
    Replace first occurrence of old_str with new_str in file.
    Snapshots before patching for /undo support.
    """
    p = Path(path).expanduser()
    if not p.exists():
        # Try relative to cwd
        import os
        p = Path(os.getcwd()) / path
    if not p.exists():
        return f"[ERROR] File not found: {path}"

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"[ERROR] Could not read {path}: {e}"

    count = content.count(old_str)
    if count == 0:
        # Give helpful context
        lines = content.splitlines()
        return (
            f"[ERROR] String not found in {path}.\n"
            f"File has {len(lines)} lines. "
            f"Make sure the old_str matches exactly including whitespace."
        )
    
    if count > 1:
        lines = content.splitlines()
        return (
            f"[ERROR] String found {count} times in {path}. "
            f"Provide more context in 'old_str' to make it unique.\n"
            f"File has {len(lines)} lines."
        )

    # Show diff preview
    new_content = content.replace(old_str, new_str, 1)

    if AGENT_CONFIG.get("confirm_write"):
        warning(f"About to patch: {path}")
        # Show context around the change
        old_lines = old_str.splitlines()
        new_lines = new_str.splitlines()
        print(f"  Removing: {repr(old_str[:80])}")
        print(f"  Adding:   {repr(new_str[:80])}")
        if not ask_confirm("Apply patch?"):
            return "[CANCELLED] Patch cancelled."

    # Pre-patch syntax check for Python files: reject patches that break syntax
    if p.suffix == '.py':
        try:
            from core.linter import check_syntax
            syn_err = check_syntax(new_content, str(p))
            if syn_err:
                return (
                    f"[ERROR] Patch would introduce syntax error: {syn_err}\n"
                    "Fix the syntax in your patch and try again. "
                    "Consider using write_file to replace the entire file instead."
                )
        except Exception:
            pass  # linter unavailable — allow patch

    snapshot(str(p))
    try:
        p.write_text(new_content, encoding="utf-8")
        changed_lines = abs(len(new_content.splitlines()) - len(content.splitlines()))
        return f"Patched {path} ({len(old_str)} chars → {len(new_str)} chars)"
    except Exception as e:
        return f"[ERROR] Could not write {path}: {e}"
