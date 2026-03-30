"""
Mapping rules: normalized intermediate → Codey-v2 tool_calls list.

Each rule function receives the intermediate dict and returns a list of
tool call dicts, or None if the record cannot be mapped.
"""

import re
import json
from typing import Dict, List, Optional

from ..normalization.classifier import (
    SHELL_COMMAND, FILE_WRITE, FILE_PATCH, FILE_READ,
    CODE_GENERATION, MULTI_STEP, NOTE_SAVE, UNKNOWN,
    detect_language, language_to_extension,
)
from .termux import normalize_command

# ── Tool name mapping for function-calling datasets ──────────────────────────
# Maps common API/function names → Codey-v2 tool name
_FC_NAME_MAP = [
    (re.compile(r"execut|run_code|run_script|run_command|invoke", re.I), "shell"),
    (re.compile(r"write_file|create_file|save_file|write_to|output_file", re.I), "write_file"),
    (re.compile(r"read_file|open_file|get_file|load_file|fetch_file", re.I), "read_file"),
    (re.compile(r"patch_file|edit_file|modify_file|update_file|change_file", re.I), "patch_file"),
    (re.compile(r"append_file|add_to_file", re.I), "append_file"),
    (re.compile(r"list_dir|list_files|list_directory|ls\b", re.I), "list_dir"),
    (re.compile(r"search_files|find_file|find_files|glob", re.I), "search_files"),
    (re.compile(r"remember|note_save|save_note|store_fact|memorize", re.I), "note_save"),
    (re.compile(r"forget|note_forget|remove_note|delete_note", re.I), "note_forget"),
    # Generic "install" → shell pkg install
    (re.compile(r"install_package|install_lib|install_dep", re.I), "shell"),
]

# File extension → default filename stem
_LANG_DEFAULTS = {
    "python":     "solution",
    "javascript": "solution",
    "typescript": "solution",
    "bash":       "script",
    "rust":       "main",
    "java":       "Solution",
    "go":         "main",
    "ruby":       "solution",
    "sql":        "query",
}


def _infer_tool_name(function_name: str) -> Optional[str]:
    """Map a generic function name to a Codey-v2 tool name."""
    for pattern, tool in _FC_NAME_MAP:
        if pattern.search(function_name):
            return tool
    return None


def _infer_path(instruction: str, language: Optional[str], code: str) -> str:
    """
    Infer a file path from instruction + language.

    Priority:
      1. Explicit filename in instruction ("create hello.py")
      2. Function name extracted from code ("def my_func" → my_func.py)
      3. Language default (solution.py)
    """
    # 1. Explicit filename in instruction
    file_match = re.search(r"\b([\w\-]+\.\w{1,6})\b", instruction)
    if file_match:
        candidate = file_match.group(1)
        # Filter out things like "e.g." or "i.e."
        if len(candidate) > 4 and "." in candidate:
            return candidate

    # 2. Extract function/class name from code
    fn_match = re.search(r"^(?:def|class|function|func)\s+(\w+)", code, re.MULTILINE)
    if fn_match:
        name = fn_match.group(1).lower()
        ext  = language_to_extension(language)
        if name not in ("main", "solution", "answer", "func"):
            return f"{name}{ext}"

    # 3. Default
    ext  = language_to_extension(language)
    stem = _LANG_DEFAULTS.get(language or "", "solution")
    return f"{stem}{ext}"


def _extract_code_content(raw_response: str) -> str:
    """Strip code fence markers and return clean code."""
    m = re.search(r"```(?:\w+)?\n(.*?)```", raw_response, re.DOTALL)
    if m:
        return m.group(1).strip()
    return raw_response.strip()


def _build_test_file(tests, entry_point: str = "", language: str = "python") -> Optional[str]:
    """Build a runnable test file from a test list or test string."""
    if not tests:
        return None

    if isinstance(tests, str):
        # Already a test function body (HumanEval/BigCodeBench style)
        ext = language_to_extension(language)
        stem = _LANG_DEFAULTS.get(language, "solution")
        imports = f"from {stem} import {entry_point}\n\n" if entry_point else ""
        return imports + tests + '\n\nif __name__ == "__main__":\n    check(' + (entry_point or "solution") + ')\n    print("All tests passed")\n'

    if isinstance(tests, list):
        lines = [f"from solution import *", ""]
        lines += tests
        lines += ['', 'print("All tests passed")']
        return "\n".join(lines) + "\n"

    return None


# ── Rule functions ─────────────────────────────────────────────────────────────

def rule_shell_command(intermediate: Dict) -> Optional[List[Dict]]:
    """Single shell command → one shell tool call."""
    raw = intermediate["raw_response"]
    code = _extract_code_content(raw)
    # Take first non-empty, non-comment line
    lines = [l.strip() for l in code.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return None
    command = normalize_command(lines[0])
    if not command:
        return None
    return [{"name": "shell", "args": {"command": command}}]


def rule_code_generation(intermediate: Dict) -> Optional[List[Dict]]:
    """Code response → write_file."""
    raw  = intermediate["raw_response"]
    code = _extract_code_content(raw)
    if not code:
        return None
    lang = intermediate.get("language") or detect_language(code, intermediate["instruction"])
    path = _infer_path(intermediate["instruction"], lang, code)
    return [{"name": "write_file", "args": {"path": path, "content": code + "\n"}}]


def rule_file_write(intermediate: Dict) -> Optional[List[Dict]]:
    """Explicit file write → write_file."""
    return rule_code_generation(intermediate)


def rule_file_patch(intermediate: Dict) -> Optional[List[Dict]]:
    """
    Patch instruction → patch_file.

    Tries to extract old/new from the response. Falls back to write_file
    if the diff can't be parsed.
    """
    raw  = intermediate["raw_response"]
    code = _extract_code_content(raw)

    # Look for unified diff or explicit old/new markers
    diff_match = re.search(
        r"(?:^|\n)[-<]\s*(.*?)(?:\n[+>]\s*(.*?))?(?:\n|$)",
        raw, re.DOTALL,
    )

    extra = intermediate.get("_extra", {})
    buggy = extra.get("buggy", "")

    if buggy and code:
        # HumanEvalPack fix task: buggy → canonical
        path = _infer_path(
            intermediate["instruction"],
            intermediate.get("language"),
            code,
        )
        return [{"name": "patch_file", "args": {
            "path": path,
            "old_str": buggy.strip(),
            "new_str": code.strip(),
        }}]

    # Can't reliably extract old/new — fall back to write_file
    return rule_code_generation(intermediate)


def rule_file_read(intermediate: Dict) -> Optional[List[Dict]]:
    """Read instruction → read_file."""
    instr = intermediate["instruction"]
    file_match = re.search(r"\b([\w\-/]+\.\w{1,6})\b", instr)
    path = file_match.group(1) if file_match else "."
    return [{"name": "read_file", "args": {"path": path}}]


def rule_note_save(intermediate: Dict) -> Optional[List[Dict]]:
    """Remember/note instruction → note_save."""
    instr = intermediate["instruction"]
    # Try to extract key=value from instruction
    kv = re.search(r"(?:remember|note|store)[:\s]+(.+?)(?:\s*=\s*|\s+is\s+|\s*:\s*)(.+)", instr, re.I)
    if kv:
        return [{"name": "note_save", "args": {"key": kv.group(1).strip(), "value": kv.group(2).strip()}}]
    # Fallback: whole instruction as key, response as value
    raw = intermediate["raw_response"].strip()[:200]
    return [{"name": "note_save", "args": {"key": instr[:80], "value": raw}}]


def rule_mbpp(intermediate: Dict) -> Optional[List[Dict]]:
    """MBPP: write solution + write test + shell run."""
    code  = _extract_code_content(intermediate["raw_response"])
    tests = intermediate.get("_extra", {}).get("test_list", [])
    if not code:
        return None

    lang = intermediate.get("language", "python")
    path = _infer_path(intermediate["instruction"], lang, code)

    tool_calls = [
        {"name": "write_file", "args": {"path": path, "content": code + "\n"}},
    ]

    test_content = _build_test_file(tests)
    if test_content:
        tool_calls.append({"name": "write_file", "args": {"path": "test_solution.py", "content": test_content}})
        tool_calls.append({"name": "shell",      "args": {"command": "python test_solution.py"}})

    return tool_calls


def rule_humaneval(intermediate: Dict) -> Optional[List[Dict]]:
    """HumanEval / BigCodeBench: write solution + write test + shell run."""
    code  = _extract_code_content(intermediate["raw_response"])
    extra = intermediate.get("_extra", {})
    test  = extra.get("test", "")
    entry = extra.get("entry_point", "")

    if not code:
        return None

    lang = intermediate.get("language", "python")
    path = _infer_path(intermediate["instruction"], lang, code)

    tool_calls = [
        {"name": "write_file", "args": {"path": path, "content": code + "\n"}},
    ]

    test_content = _build_test_file(test, entry, lang)
    if test_content:
        tool_calls.append({"name": "write_file", "args": {"path": "test_solution.py", "content": test_content}})
        tool_calls.append({"name": "shell",      "args": {"command": "python test_solution.py"}})

    return tool_calls


def rule_function_call_json(intermediate: Dict) -> Optional[List[Dict]]:
    """
    Function-calling datasets (Glaive, Hermes): parse JSON function call
    and map to Codey-v2 tool.
    """
    raw = intermediate["raw_response"].strip()

    # Try to parse as JSON
    try:
        fc = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the string
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            fc = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None

    func_name = fc.get("name", fc.get("function", ""))
    raw_args  = fc.get("arguments", fc.get("args", fc.get("parameters", {})))

    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError:
            raw_args = {"command": raw_args}

    if not isinstance(raw_args, dict):
        raw_args = {}

    # Map function name to Codey-v2 tool
    tool_name = _infer_tool_name(func_name)
    if not tool_name:
        return None

    # Build args for the mapped tool
    tool_args = _map_fc_args(tool_name, func_name, raw_args)
    if tool_args is None:
        return None

    return [{"name": tool_name, "args": tool_args}]


def _map_fc_args(tool_name: str, orig_name: str, raw_args: Dict) -> Optional[Dict]:
    """Translate generic function args to the required Codey-v2 tool args."""
    if tool_name == "shell":
        # Find the command value — try common key names
        cmd = (
            raw_args.get("command") or raw_args.get("cmd") or
            raw_args.get("code") or raw_args.get("script") or
            raw_args.get("file") or raw_args.get("path") or
            # If executing a file, build: python <file>
            next(iter(raw_args.values()), None)
        )
        if not cmd:
            return None
        # If it's a file path, run it
        if re.search(r"\.\w{1,6}$", str(cmd)):
            cmd = f"python {cmd}"
        return {"command": normalize_command(str(cmd))}

    elif tool_name == "write_file":
        content = (
            raw_args.get("content") or raw_args.get("code") or
            raw_args.get("text") or raw_args.get("data") or ""
        )
        path = (
            raw_args.get("path") or raw_args.get("filename") or
            raw_args.get("file") or raw_args.get("name") or "output.txt"
        )
        return {"path": str(path), "content": str(content)}

    elif tool_name == "read_file":
        path = (
            raw_args.get("path") or raw_args.get("file") or
            raw_args.get("filename") or "."
        )
        return {"path": str(path)}

    elif tool_name == "patch_file":
        return {
            "path":    str(raw_args.get("path", raw_args.get("file", "file.py"))),
            "old_str": str(raw_args.get("old_str", raw_args.get("old", raw_args.get("before", "")))),
            "new_str": str(raw_args.get("new_str", raw_args.get("new", raw_args.get("after", "")))),
        }

    elif tool_name == "list_dir":
        return {"path": str(raw_args.get("path", raw_args.get("directory", ".")))}

    elif tool_name == "search_files":
        return {
            "pattern": str(raw_args.get("pattern", raw_args.get("query", raw_args.get("glob", "*")))),
            "path":    str(raw_args.get("path", ".")),
        }

    elif tool_name == "note_save":
        return {
            "key":   str(raw_args.get("key", raw_args.get("name", "fact"))),
            "value": str(raw_args.get("value", raw_args.get("content", ""))),
        }

    elif tool_name == "note_forget":
        return {"key": str(raw_args.get("key", raw_args.get("name", "")))}

    return None


def rule_xlam_answers(intermediate: Dict) -> Optional[List[Dict]]:
    """
    xLAM / APIGen: parse the answers JSON array directly.
    Each entry: {"name": "...", "arguments": {...}}
    """
    raw = intermediate["raw_response"].strip()
    try:
        answers = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(answers, list):
        answers = [answers]

    tool_calls = []
    for entry in answers:
        func_name = entry.get("name", "")
        raw_args  = entry.get("arguments", entry.get("args", {}))

        if isinstance(raw_args, str):
            try:
                raw_args = json.loads(raw_args)
            except json.JSONDecodeError:
                raw_args = {"command": raw_args}

        tool_name = _infer_tool_name(func_name)
        if not tool_name:
            continue

        tool_args = _map_fc_args(tool_name, func_name, raw_args or {})
        if tool_args:
            tool_calls.append({"name": tool_name, "args": tool_args})

    return tool_calls if tool_calls else None


def rule_code_with_execution(intermediate: Dict) -> Optional[List[Dict]]:
    """Code-Feedback: write_file + shell execute."""
    code  = _extract_code_content(intermediate["raw_response"])
    extra = intermediate.get("_extra", {})

    if not code:
        return None

    lang = intermediate.get("language", "python")
    path = _infer_path(intermediate["instruction"], lang, code)

    tool_calls = [
        {"name": "write_file", "args": {"path": path, "content": code + "\n"}},
    ]

    # Add execution step if feedback shows it was executed
    feedback = extra.get("code_feedback", [])
    if feedback:
        fb = feedback[0]
        run_cmd = fb.get("input", "").strip()
        if run_cmd:
            run_cmd = normalize_command(run_cmd)
            tool_calls.append({"name": "shell", "args": {"command": run_cmd}})
        else:
            tool_calls.append({"name": "shell", "args": {"command": f"python {path}"}})

    return tool_calls


# ── Rule dispatcher ───────────────────────────────────────────────────────────

_SCHEMA_RULE_MAP = {
    "mbpp":              rule_mbpp,
    "humaneval":         rule_humaneval,
    "bigcodebench":      rule_humaneval,
    "function_call_json": rule_function_call_json,
    "xlam_answers":      rule_xlam_answers,
    "code_with_execution": rule_code_with_execution,
    "patch":             rule_file_patch,
}

_TYPE_RULE_MAP = {
    SHELL_COMMAND:   rule_shell_command,
    FILE_WRITE:      rule_file_write,
    FILE_PATCH:      rule_file_patch,
    FILE_READ:       rule_file_read,
    CODE_GENERATION: rule_code_generation,
    NOTE_SAVE:       rule_note_save,
    MULTI_STEP:      rule_code_generation,  # fallback; multi-step parsed separately
}


def apply_rules(intermediate: Dict) -> Optional[List[Dict]]:
    """
    Apply the correct rule to an intermediate record.

    Checks schema_type first (dataset-specific rules take priority),
    then falls back to response_type-based rules.
    """
    schema = intermediate.get("_extra", {}).get("schema_type", "")
    if schema and schema in _SCHEMA_RULE_MAP:
        return _SCHEMA_RULE_MAP[schema](intermediate)

    resp_type = intermediate.get("response_type", UNKNOWN)
    rule_fn   = _TYPE_RULE_MAP.get(resp_type, rule_code_generation)
    return rule_fn(intermediate)
