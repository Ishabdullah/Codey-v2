"""
Response type classifier.

Given a raw response string, determines what kind of action it represents
so the transformer can map it to the right Codey-v2 tool.
"""

import re
from typing import Optional

# Response types
SHELL_COMMAND   = "shell_command"
FILE_WRITE      = "file_write"
FILE_PATCH      = "file_patch"
FILE_READ       = "file_read"
CODE_GENERATION = "code_generation"
MULTI_STEP      = "multi_step"
NOTE_SAVE       = "note_save"
UNKNOWN         = "unknown"

# Single-token commands that strongly signal a shell command response
_SHELL_PREFIXES = {
    "pkg", "pip", "pip3", "python", "python3", "node", "npm", "git",
    "ls", "cd", "mkdir", "rm", "cp", "mv", "cat", "echo", "chmod",
    "apt", "apt-get", "brew", "curl", "wget", "tar", "unzip", "zip",
    "grep", "find", "sed", "awk", "make", "cmake", "cargo", "go",
    "java", "javac", "bash", "sh", "zsh", "termux-setup-storage",
    "termux-notification", "termux-clipboard-get", "termux-clipboard-set",
    "termux-battery-status", "termux-camera-photo", "adb",
}

# Code block language tags
_CODE_BLOCK_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)

# Numbered/bulleted step patterns
_STEP_RE = re.compile(
    r"(?:^|\n)\s*(?:\d+[\.\):]|[-*•])\s+\S",
    re.MULTILINE,
)

# File creation keywords in instructions
_FILE_CREATE_RE = re.compile(
    r"\b(?:create|write|make|generate|build|produce|save)\b.*?\b\w+\.\w{1,6}\b",
    re.IGNORECASE,
)
_FILE_PATCH_RE = re.compile(
    r"\b(?:fix|update|modify|change|edit|patch|refactor|replace|rename)\b",
    re.IGNORECASE,
)
_NOTE_RE = re.compile(
    r"\b(?:remember|note|store|save.*fact|don.t forget|keep in mind)\b",
    re.IGNORECASE,
)
_READ_RE = re.compile(
    r"\b(?:read|open|show|display|print|view|cat|inspect|examine)\b.*?\b\w+\.\w{1,6}\b",
    re.IGNORECASE,
)


def classify_response(response: str, instruction: str = "") -> str:
    """
    Classify what type of action a response represents.

    Args:
        response:    The raw response/output text
        instruction: The original instruction (used as additional signal)

    Returns:
        One of the response type constants above
    """
    if not response:
        return UNKNOWN

    resp = response.strip()
    instr = instruction.strip().lower()

    # ── Multi-step: numbered list with 2+ action steps ────────────────────────
    steps = _STEP_RE.findall(resp)
    if len(steps) >= 2 and len(resp) > 100:
        return MULTI_STEP

    # ── Note save: "remember X" instructions ──────────────────────────────────
    if _NOTE_RE.search(instr):
        return NOTE_SAVE

    # ── Read file: instruction asks to read/display a file ────────────────────
    if _READ_RE.search(instr) and not _FILE_CREATE_RE.search(instr):
        return FILE_READ

    # ── Shell command: single line starting with a known CLI command ──────────
    lines = [l.strip() for l in resp.splitlines() if l.strip()]
    if lines:
        first_word = lines[0].split()[0].lstrip("$").lstrip(">").strip()
        if first_word in _SHELL_PREFIXES and len(lines) <= 3:
            return SHELL_COMMAND

    # ── Code block: ```lang ... ``` ────────────────────────────────────────────
    code_match = _CODE_BLOCK_RE.search(resp)
    if code_match:
        lang = (code_match.group(1) or "").lower()
        code = code_match.group(2).strip()
        if lang in ("bash", "sh", "shell", "zsh"):
            # Single-command shell block
            cmd_lines = [l for l in code.splitlines() if l.strip() and not l.startswith("#")]
            if len(cmd_lines) <= 3:
                return SHELL_COMMAND
        # Multi-line code or specific language → write_file
        if code:
            if _FILE_PATCH_RE.search(instr):
                return FILE_PATCH
            return FILE_WRITE

    # ── Raw code: contains def/class/function signatures ──────────────────────
    if re.search(r"\b(def |class |function |import |from .+ import)\b", resp):
        if _FILE_PATCH_RE.search(instr):
            return FILE_PATCH
        return CODE_GENERATION

    # ── Patch: instruction explicitly asks to fix/edit ────────────────────────
    if _FILE_PATCH_RE.search(instr):
        return FILE_PATCH

    # ── File create: instruction names a file to create ───────────────────────
    if _FILE_CREATE_RE.search(instr):
        return FILE_WRITE

    # ── Single line that looks runnable ───────────────────────────────────────
    if len(lines) == 1 and not resp.startswith(("{", "[")):
        return SHELL_COMMAND

    return CODE_GENERATION


def detect_language(code: str, instruction: str = "") -> Optional[str]:
    """
    Detect programming language from code content or instruction.

    Returns lowercase language name or None.
    """
    instr_lower = instruction.lower()

    # Instruction keywords
    lang_keywords = {
        "python": "python", "py ": "python",
        "javascript": "javascript", "js ": "javascript", "node": "javascript",
        "typescript": "typescript", "ts ": "typescript",
        "bash": "bash", "shell": "bash", "sh ": "bash",
        "rust": "rust", "java ": "java", "golang": "go", "go ": "go",
        "ruby": "ruby", "php": "php", "sql": "sql", "c++": "cpp",
        "c#": "csharp", "kotlin": "kotlin", "swift": "swift",
    }
    for kw, lang in lang_keywords.items():
        if kw in instr_lower:
            return lang

    # Code content signals
    if re.search(r"^def |^class |^import |^from .+ import", code, re.MULTILINE):
        return "python"
    if re.search(r"^function |^const |^let |^var |=>", code, re.MULTILINE):
        return "javascript"
    if re.search(r"^fn |^use |^impl |^struct ", code, re.MULTILINE):
        return "rust"
    if re.search(r"^public class |^import java", code, re.MULTILINE):
        return "java"
    if re.search(r"^package main|^func ", code, re.MULTILINE):
        return "go"
    if re.search(r"^#!/.*(?:bash|sh)\b|^pkg |^apt ", code, re.MULTILINE):
        return "bash"

    return None


def language_to_extension(lang: Optional[str]) -> str:
    """Map language name to file extension."""
    mapping = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "bash": ".sh",
        "rust": ".rs",
        "java": ".java",
        "go": ".go",
        "ruby": ".rb",
        "php": ".php",
        "sql": ".sql",
        "cpp": ".cpp",
        "csharp": ".cs",
        "kotlin": ".kt",
        "swift": ".swift",
    }
    return mapping.get(lang or "", ".py")
