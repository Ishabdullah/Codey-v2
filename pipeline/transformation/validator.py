"""
Tool call schema validator.

Ensures every generated tool call conforms exactly to the Codey-v2 spec
before it enters the output JSONL or vector store.
"""

from typing import Dict, List, Tuple

# Canonical tool registry with required arg keys
TOOL_SCHEMAS: Dict[str, List[str]] = {
    "shell":        ["command"],
    "write_file":   ["path", "content"],
    "patch_file":   ["path", "old_str", "new_str"],
    "read_file":    ["path"],
    "append_file":  ["path", "content"],
    "list_dir":     [],          # path is optional
    "search_files": ["pattern"], # path is optional
    "note_save":    ["key", "value"],
    "note_forget":  ["key"],
}

VALID_TOOL_NAMES = set(TOOL_SCHEMAS.keys())

# Shell metacharacters that the Codey-v2 shell tool blocks (mirrors shell_tools.py)
_SHELL_METACHARACTERS = [';', '&&', '||', '|', '`', '$(', '${', '<(', '>(', '\n', '\r']

# Max content sizes (characters) — prevent enormous records in the index
_MAX_CONTENT_LEN  = 50_000
_MAX_COMMAND_LEN  = 500
_MAX_PATH_LEN     = 256

# Placeholder indicators
_PLACEHOLDERS = {"...", "TODO", "PLACEHOLDER", "<content>", "<code>", "pass"}


def validate_tool_call(tc: Dict) -> Tuple[bool, str]:
    """
    Validate a single tool call dict.

    Returns:
        (is_valid: bool, error_message: str)
        If valid: (True, "")
    """
    name = tc.get("name", "")
    args = tc.get("args", {})

    # Tool name
    if name not in VALID_TOOL_NAMES:
        return False, f"Unknown tool name: '{name}'"

    # Args must be a dict
    if not isinstance(args, dict):
        return False, f"args must be a dict, got {type(args).__name__}"

    # Required keys
    required = TOOL_SCHEMAS[name]
    for key in required:
        if key not in args:
            return False, f"Tool '{name}' missing required arg: '{key}'"
        val = args[key]
        if not isinstance(val, str):
            return False, f"Tool '{name}' arg '{key}' must be str, got {type(val).__name__}"
        if not val.strip():
            return False, f"Tool '{name}' arg '{key}' is empty"

    # Tool-specific checks
    if name == "shell":
        cmd = args.get("command", "")
        if len(cmd) > _MAX_COMMAND_LEN:
            return False, f"shell command too long ({len(cmd)} chars)"
        for meta in _SHELL_METACHARACTERS:
            if meta in cmd:
                return False, f"shell command contains blocked metacharacter: {repr(meta)}"

    elif name in ("write_file", "append_file"):
        content = args.get("content", "")
        if content.strip() in _PLACEHOLDERS:
            return False, "write_file content is a placeholder stub"
        if len(content) > _MAX_CONTENT_LEN:
            # Truncate rather than reject
            args["content"] = content[:_MAX_CONTENT_LEN] + "\n# [truncated by pipeline]\n"

        path = args.get("path", "")
        if len(path) > _MAX_PATH_LEN:
            return False, f"path too long ({len(path)} chars)"
        # Prevent absolute paths pointing outside project
        if path.startswith("/") and not path.startswith("/data/data/com.termux"):
            return False, f"absolute path outside Termux: {path}"

    elif name == "patch_file":
        if args.get("old_str", "") == args.get("new_str", ""):
            return False, "patch_file old_str and new_str are identical"

    return True, ""


def validate_record(tool_calls: List[Dict]) -> Tuple[bool, str]:
    """Validate an entire tool_calls list."""
    if not tool_calls:
        return False, "tool_calls list is empty"
    if len(tool_calls) > 10:
        return False, f"too many tool calls ({len(tool_calls)}) in one record"
    for i, tc in enumerate(tool_calls):
        ok, err = validate_tool_call(tc)
        if not ok:
            return False, f"tool_calls[{i}]: {err}"
    return True, ""


def coerce_args(tc: Dict) -> Dict:
    """
    Coerce all arg values to strings and normalise common variations.

    - "arguments" key → "args"
    - numeric/bool values → str
    """
    # Accept both "args" and "arguments"
    args = tc.get("args") or tc.get("arguments") or {}
    coerced = {k: str(v) for k, v in args.items()}
    return {"name": tc.get("name", ""), "args": coerced}
