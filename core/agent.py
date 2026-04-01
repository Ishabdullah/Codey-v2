import json
import re
import time
from core.inference_v2 import infer
from core.context import build_file_context_block, auto_load_from_prompt, list_loaded
from core.project import get_project_summary
from core.codeymd import read_codeymd, find_codeymd
from core.summarizer import should_summarize, summarize_history
from core.tokens import get_context_usage, usage_bar
from core.learning import get_learning_manager
from tools.file_tools import tool_read_file, tool_write_file, tool_append_file, tool_list_dir
from tools.patch_tools import tool_patch_file
from tools.shell_tools import shell, search_files
from utils.logger import tool_call, tool_result, warning, separator, info, success
from utils.config import AGENT_CONFIG, RECURSIVE_CONFIG
from core.display import show_file_write, show_patch, show_shell, show_tool_generic, show_response

# Learning manager for adaptive behavior
_learning = None

def _get_learning():
    """Get learning manager singleton."""
    global _learning
    if _learning is None:
        _learning = get_learning_manager()
    return _learning

def _note_save(args):
    from core.notes import add_note
    add_note(args["key"], args["value"])
    return f"Remembered: {args['key']} = {args['value']}"

def _note_forget(args):
    from core.notes import remove_note
    if remove_note(args["key"]):
        return f"Forgot: {args['key']}"
    return f"No note found for: {args['key']}"

TOOLS = {
    "read_file":    lambda args: tool_read_file(args["path"]),
    "write_file":   lambda args: tool_write_file(args["path"], args["content"]),
    "patch_file":   lambda args: tool_patch_file(args["path"], args["old_str"], args["new_str"]),
    "append_file":  lambda args: tool_append_file(args["path"], args["content"]),
    "list_dir":     lambda args: tool_list_dir(args.get("path", ".")),
    # Route through AGENT_CONFIG["_shell_fn"] when set (e.g. daemon allowlist guard).
    # Falls back to the standard shell() when no override is installed.
    "shell":        lambda args: (AGENT_CONFIG.get("_shell_fn") or shell)(args["command"]),
    "search_files": lambda args: search_files(args["pattern"], args.get("path", ".")),
    "note_save":    _note_save,
    "note_forget":  _note_forget,
}
ROGUE_TAG_MAP = {
    "write_file": "write_file", "read_file": "read_file",
    "patch_file": "patch_file", "shell": "shell",
    "append_file": "append_file", "list_dir": "list_dir",
    "search_files": "search_files",
    "note_save": "note_save", "note_forget": "note_forget",
}

HALLUCINATION_MARKERS = [
    # ChatML tokens — always strip (model leaking special tokens)
    "<|im_start|>", "<|im_end|>",
    # System-prompt echo — model regurgitating its own context (## headers)
    "\n## Loaded Files", "\n## Project Memory", "\n## Current Project",
    "\n## User Notes", "\n## Project Map", "\n## User Preferences",
    "\n## Relevant Skills", "\n## Reference Material", "\n## Repo Map",
    # CODEY.md echo — model regurgitating project memory (# headers)
    "\n# Project", "\n# Stack", "\n# Structure", "\n# Commands",
    "\n# Conventions", "\n# Notes",
    # CODEY.md list items — model echoing config lines
    "\n- Code style:", "\n- Naming:", "\n- Logging:", "\n- Imports:",
    # Code leakage — model echoing source after prose (common with small models)
    "\nfrom core.", "\nfrom utils.", "\nfrom prompts.", "\nfrom tools.",
    "\nimport core.", "\nimport utils.",
]

# Subset of markers safe to use as server-side stop sequences.
# These stop llama-server generation before leakage gets streamed to stdout.
_LEAK_STOP_SEQUENCES = [
    "\n## Loaded Files", "\n## Project Memory", "\n## Current Project",
    "\n## User Notes", "\n## Project Map", "\n## User Preferences",
    "\n## Relevant Skills", "\n## Reference Material", "\n## Repo Map",
    "\n# Project", "\n# Stack", "\n# Structure", "\n# Commands",
    "\n# Conventions", "\n# Notes",
    "\n- Code style:", "\n- Naming:", "\n- Logging:", "\n- Imports:",
    "\nfrom core.", "\nfrom utils.", "\nfrom prompts.", "\nfrom tools.",
    "\nimport core.", "\nimport utils.",
]

def clean_response(text):
    for marker in HALLUCINATION_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip()

def extract_json(raw):
    """
    Extract JSON from LLM output. Handles trailing commas, missing closing
    braces, literal newlines inside strings, and Python triple-quotes.
    """
    raw = raw.strip()

    # Fix Python triple-quotes → JSON strings (common 7B model error).
    # The model writes """content""" instead of a proper JSON string.
    # Handles nested docstrings inside the code content.
    def _fix_triple_quotes(s):
        # The original s.find('"""') always matched the FIRST triple-quote
        # found after the opening — which is the docstring opener inside the
        # code content, not the real closing delimiter.  Fix: scan all """
        # positions and pick the LAST one followed by } or , (JSON context),
        # so nested docstrings in the code are captured as part of the content.
        result = []
        i = 0
        while i < len(s):
            if s[i:i+3] == '"""':
                rest = s[i + 3:]
                positions = [m.start() for m in re.finditer(r'"""', rest)]
                closing_pos = -1
                for pos in reversed(positions):
                    after = rest[pos + 3:].lstrip()
                    if not after or after[0] in ',}':
                        closing_pos = pos
                        break
                if closing_pos == -1 and positions:
                    closing_pos = positions[-1]
                if closing_pos != -1:
                    inner = rest[:closing_pos]
                    i = i + 3 + closing_pos + 3
                else:
                    inner = rest
                    i = len(s)
                # Encode raw content as a proper JSON string
                inner = inner.replace('\\', '\\\\')
                inner = inner.replace('"', '\\"')
                inner = inner.replace('\n', '\\n')
                inner = inner.replace('\t', '\\t')
                inner = inner.replace('\r', '\\r')
                result.append('"' + inner + '"')
            else:
                result.append(s[i])
                i += 1
        return ''.join(result)

    if '"""' in raw:
        raw = _fix_triple_quotes(raw)

    if not raw.startswith('{'):
        # Try to find the start of a JSON block
        idx = raw.find('{')
        if idx != -1:
            raw = raw[idx:]
        else:
            return None

    # Improved depth tracking that ignores braces inside strings
    depth = 0
    in_string = False
    escape = False
    end = 0

    for i, ch in enumerate(raw):
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

    if end == 0:
        # If we didn't find the end, maybe the model just outputted incomplete JSON
        # Let's try to close it as a last resort
        if depth > 0:
            candidate = raw + ("}" * depth)
        else:
            return None
    else:
        candidate = raw[:end]

    # Clean candidate for common LLM artifacts: trailing commas
    cleaned = re.sub(r',\s*([}\]])', r'\1', candidate)

    # Fix literal newlines inside JSON strings (common 7B model error)
    # Replace actual newlines inside string values with \n
    def _fix_literal_newlines(s):
        result = []
        in_str = False
        esc = False
        for ch in s:
            if esc:
                result.append(ch)
                esc = False
                continue
            if ch == '\\':
                result.append(ch)
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                result.append(ch)
                continue
            if in_str and ch == '\n':
                result.append('\\n')
                continue
            result.append(ch)
        return ''.join(result)

    def _fix_unquoted_values(s):
        """Quote unquoted string values emitted by smaller models.

        Handles cases like {"path": /tmp/foo.py} or {"cmd": ls -la}
        where the model omits quotes around non-JSON-primitive values.
        """
        def _replacer(m):
            key_part = m.group(1)
            val = m.group(2).strip()
            # Leave JSON primitives alone
            if val in ('true', 'false', 'null'):
                return m.group(0)
            if re.match(r'^-?\d+\.?\d*$', val):
                return m.group(0)
            escaped = val.replace('\\', '\\\\').replace('"', '\\"')
            return key_part + '"' + escaped + '"'
        # Match ": unquoted_value  where value is not already quoted/object/array
        return re.sub(
            r'(":\s*)([^",\{\[\s][^,\}]*?)(?=\s*[,\}])',
            _replacer,
            s,
        )

    # Try raw candidate first, then cleaned, then newline-fixed, then unquoted-fixed
    for s in [candidate, cleaned, _fix_literal_newlines(cleaned),
              _fix_unquoted_values(cleaned)]:
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            pass

    return None

def parse_tool_call(text):
    # ── Primary: JSON format in <tool> tags ──────────────────────────
    match = re.search(r"<tool>\s*(\{.*)", text, re.DOTALL)
    if match:
        result = extract_json(match.group(1))
        if result and "name" in result:
            return result
    # Rogue tags: <write_file>{json}</write_file> etc.
    for tag, canonical in ROGUE_TAG_MAP.items():
        match = re.search(r"<" + tag + r">\s*(\{.*)", text, re.DOTALL)
        if match:
            inner = extract_json(match.group(1))
            if inner:
                if "name" in inner:
                    return inner
                return {"name": canonical, "args": inner}

    # ── Fallback: block-style tags (no JSON escaping) ────────────────
    # <write_file path="...">...code...</write_file>
    m = re.search(r'<write_file\s+path="([^"]+)">\s*\n?(.*?)(?:</write_file>|\Z)', text, re.DOTALL)
    if m and m.group(2).strip():
        return {"name": "write_file", "args": {"path": m.group(1), "content": m.group(2).strip()}}

    return None

def _format_tool_for_history(tool_dict):
    """Format a tool call for conversation history."""
    return "<tool>\n" + json.dumps(tool_dict) + "\n</tool>"


def execute_tool(tool_dict):
    """
    Execute a tool call with learning integration.
    
    Learns from:
    - File operations (for preference learning)
    - Errors (for error database)
    - Strategy effectiveness (for adaptive recovery)
    """
    name = tool_dict.get("name", "")
    args = tool_dict.get("args", {})
    learning = _get_learning()
    
    if name not in TOOLS:
        return "[ERROR] Unknown tool: " + name
    
    start_time = time.time()
    
    try:
        # For write_file: read old content for diff display BEFORE the write,
        # show the display panel immediately after, then release old_content.
        # This avoids holding both old and new content for the entire function.
        _is_write = name == "write_file"
        _is_patch = name == "patch_file"
        old_content = None
        if _is_write:
            from pathlib import Path as _P
            p = _P(args.get("path", ""))
            if p.exists():
                try: old_content = p.read_text()
                except: pass

        result = TOOLS[name](args)
        duration = time.time() - start_time

        # Display IMMEDIATELY after write — then release old_content so GC
        # can reclaim it before linting/learning/memory-loading pile on.
        try:
            if _is_write:
                show_file_write(args.get("path",""), args.get("content",""), old_content)
                del old_content  # release ~10-50KB before next steps
            elif _is_patch:
                show_patch(args.get("path",""), args.get("old_str",""), args.get("new_str",""))
            elif name == "shell":
                is_err = is_error(result, "shell")
                show_shell(args.get("command",""), result, error=is_err)
            elif name != "read_file":
                show_tool_generic(name, args, result)
        except Exception:
            pass  # display failure must not mask a successful tool result
        old_content = None  # ensure released even if display was skipped

        # ── Post-write lint (replaces pre-write syntax check + post-write lint)
        # Single pass — the linter reads from disk (no extra content copy).
        if (_is_write or _is_patch) and not result.startswith("[ERROR]"):
            _lpath = args.get("path", "")
            if _lpath.endswith(".py"):
                try:
                    from core.linter import run_linter, format_issues
                    _issues, _linter_used = run_linter(_lpath)
                    if _issues:
                        _errors   = [i for i in _issues if i.severity == "error"]
                        _warnings = [i for i in _issues if i.severity != "error"]
                        if _errors:
                            result += format_issues(_errors)
                        if _warnings:
                            from utils.logger import warning as _lwarn
                            _lwarn(f"[Linter/{_linter_used}] {len(_warnings)} style warning(s) in {_lpath}:")
                            for _w in _warnings[:5]:
                                _lwarn(f"  Line {_w.line}: [{_w.code}] {_w.message}")
                            if len(_warnings) > 5:
                                _lwarn(f"  ... and {len(_warnings) - 5} more (run /review for full list)")
                except Exception:
                    pass  # linter unavailable — continue normally

        # Log successful actions to episodic memory (lightweight — just a string)
        if (_is_write or _is_patch or name == "shell") and not result.startswith("[ERROR]"):
            from core.memory_v2 import memory as _mem
            _mem.log_action(name, result[:100])

        # NOTE: learning.learn_from_file is NOT called here — it's called once
        # in the agent loop after execute_tool returns, avoiding a duplicate pass.

        return result
        
    except Exception as e:
        duration = time.time() - start_time
        error_msg = str(e)
        
        # Learn from errors
        error_type = type(e).__name__
        learning.record_error(error_type, error_msg, {
            "tool": name,
            "args": args,
        })
        
        return "[ERROR] " + error_msg

def is_error(result, tool_name):
    if not isinstance(result, str):
        return False
    result_lower = result.lower()
    if "[cancelled]" in result_lower:
        return False
    # All tools: treat [ERROR] prefix as an error
    if result.startswith("[ERROR]"):
        return True
    # Shell-specific: detect Python tracebacks and command failures
    if tool_name == "shell":
        error_signals = [
            "traceback", "syntaxerror", "nameerror", "typeerror",
            "importerror", "modulenotfounderror", "indentationerror",
            "attributeerror", "valueerror", "filenotfounderror",
            "permissionerror", "error:", "exception:", "failed",
            "command not found", "no such file",
        ]
        return any(s in result_lower for s in error_signals)
    return False

def is_hallucination(response, user_message, tools_used):
    """
    Lightweight hallucination check — catches only the most obvious cases.

    With recursive self-critique (Phase 2+), most hallucination is caught
    during inference. This is a final safety net for clear false claims.

    Returns:
        Tuple of (false_file, false_run) booleans
    """
    msg_lower = user_message.lower()
    resp_lower = response.lower()

    needs_file = any(k in msg_lower for k in ["create", "write", "make", "build", "implement"])
    needs_run = any(k in msg_lower for k in ["run", "execute", "test"])

    file_done = any("write_file" in s or "patch_file" in s for s in tools_used)
    shell_done = any("shell" in s for s in tools_used)

    # Flag 1: strong past-tense completion claims with zero tool usage
    _strong_claims = ["has been created", "i created", "i've created", "has been written"]
    false_file = (needs_file and not file_done and not tools_used
                  and any(c in resp_lower for c in _strong_claims))

    # Flag 2: model showed code in markdown blocks instead of using write_file
    # (common failure mode — model "explains" instead of acting)
    if needs_file and not file_done and not tools_used and "```" in response:
        false_file = True

    false_run = (needs_run and not shell_done and not tools_used
                 and any(c in resp_lower for c in ["ran successfully", "executed successfully"]))

    return false_file, false_run

def build_system_prompt(message=""):
    """
    Alias for build_recursive_prompt(phase="draft") — kept for compatibility.
    All new call sites should use build_recursive_prompt() directly.
    """
    from prompts.layered_prompt import build_recursive_prompt
    return build_recursive_prompt(message, phase="draft")

def enrich_message(user_message):
    loaded = list_loaded()
    if not loaded:
        return user_message
    fix_keywords = [
        "fix", "correct", "bug", "wrong", "error", "broken",
        "update", "change", "edit", "modify", "patch",
        "replace", "rename", "swap", "convert", "append",
        "insert", "move", "add", "remove", "delete",
    ]
    if any(kw in user_message.lower() for kw in fix_keywords):
        return (
            user_message + "\n\n"
            "Files loaded: " + ", ".join(loaded) + ". "
            "Prefer patch_file for small edits. Use write_file only for new files or full rewrites."
        )
    return user_message

def check_git_and_offer_commit(user_message, tools_used):
    if not tools_used:
        return
    # Only offer if write_file or patch_file was used
    if not any("write_file" in s or "patch_file" in s for s in tools_used):
        return
        
    from core.githelper import is_git_repo, git_status, git_commit
    from utils.logger import confirm as ask_confirm, info, success, error
    
    if not is_git_repo():
        return
        
    status = git_status()
    if status == "Nothing to commit.":
        return
        
    info("\nChanges detected. Reviewing git status...")
    print(status)
    if ask_confirm("\nStage all and commit these changes?"):
        # Simple heuristic for commit message from user request
        msg = f"Codey: {user_message[:50]}..."
        res = git_commit(msg)
        if res.startswith("[ERROR]"):
            error(res)
        else:
            success(f"Committed: {msg}")

def _extract_peer_output_from_history(history: list, peer_name: str) -> str:
    """
    Scan conversation history backwards for the most recent output from a named
    peer CLI.  Returns the content string if found, or "" if not found.

    Matches the format produced by PeerCLIManager.summarize_result():
      "[Peer CLI — {peer_name}]\nTask: ...\nOutput:\n..."

    Fallback: if not in history (e.g. session resumed after compression),
    reads {peer_name}_design.md from the current working directory.
    """
    prefix = f"[Peer CLI — {peer_name.lower()}]"
    for msg in reversed(history):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if content.lower().startswith(prefix):
                return content
    # Disk fallback — design tasks write raw output here for cross-step durability
    import os as _os
    _design_path = _os.path.join(_os.getcwd(), f"{peer_name.lower()}_design.md")
    if _os.path.exists(_design_path):
        try:
            with open(_design_path, "r", encoding="utf-8") as _df:
                _content = _df.read().strip()
            if _content:
                info(f"[peer] Loaded {peer_name} design from {peer_name.lower()}_design.md (history fallback)")
                return _content
        except Exception:
            pass
    return ""


def _detect_peer_delegation(user_message: str):
    """
    Detect phrases like:
      "ask gemini to X"   "have claude do X"   "call qwen and X"
      "use gemini to X"   "tell claude to X"   "let qwen X"
      "get claude to X"

    Returns (peer_name, task_string) or (None, None).
    """
    _PEER_NAMES = ["claude", "gemini", "qwen"]
    _pattern = re.compile(
        r'\b(?:ask|call|have|tell|use|get|let)\s+('
        + '|'.join(_PEER_NAMES)
        + r')\s+(?:to\s+|and\s+|do\s+|to\s+do\s+|to\s+help\s+with\s+)?(.+)',
        re.IGNORECASE,
    )
    m = _pattern.search(user_message)
    if m:
        return m.group(1).lower(), m.group(2).strip()

    # Also match direct-name patterns: "gemini, X" / "qwen: X" / "claude - X"
    _direct = re.compile(
        r'^('
        + '|'.join(_PEER_NAMES)
        + r')[\s,:\-]+(.+)',
        re.IGNORECASE,
    )
    m2 = _direct.match(user_message.strip())
    if m2:
        return m2.group(1).lower(), m2.group(2).strip()

    return None, None


def _auto_apply_peer_code(peer_output, context_message=""):
    """
    Extract code blocks from peer CLI output and write them to disk.

    Primary pattern — filename header before a code block:
      **`app.py`** — description        **app.py**        `app.py`:
      ```python
      code...
      ```

    Fallback pattern — bare triple-backtick block with no filename header.
    When no filename is found in the block, the expected filename is inferred
    from `context_message` (the original user request).  Only the first
    qualifying bare block is used to avoid writing ambiguous files.

    Returns list of filenames written, or empty list if none found.
    """
    import os
    files_written = []
    _CODE_EXTS = ('.py', '.js', '.ts', '.html', '.css', '.json')

    def _safe_write(fname, code):
        """Syntax-check (Python only), then write via safety layer."""
        if fname.endswith('.py'):
            try:
                from core.linter import check_syntax
                if check_syntax(code.rstrip(), fname):
                    return False  # syntax error — skip
            except Exception:
                pass
        fpath = os.path.join(os.getcwd(), fname)
        result = tool_write_file(fpath, code.rstrip() + '\n')
        if result.startswith("[ERROR]") or result.startswith("[CANCELLED]"):
            warning(f"Failed to write {fname} from peer: {result}")
            return False
        files_written.append(fname)
        success(f"Written {fname} from peer review ({len(code)} chars)")
        return True

    # ── Primary: filename header immediately before a fenced code block ──────
    _block_re = re.compile(
        r'(?:\*{1,2}`?(\w[\w.\-]*\.\w+)`?\*{0,2}|`(\w[\w.\-]*\.\w+)`:?)'
        r'\s*(?:—[^\n]*)?\s*\n'
        r'```(?:\w+)?\n(.*?)```',
        re.DOTALL,
    )
    for m in _block_re.finditer(peer_output):
        fname = m.group(1) or m.group(2)
        code = m.group(3)
        if not fname or not code or len(code.strip()) < 50:
            continue
        if not any(fname.endswith(ext) for ext in _CODE_EXTS):
            continue
        _safe_write(fname, code)

    # ── Secondary: fuzzy heading patterns (### File: x.py / ## x.py / File: x.py)
    if not files_written:
        _fuzzy_re = re.compile(
            r'(?:#{1,4}\s+(?:[Ff]ile:\s*)?|[Ff]ile:\s*)([\w][\w.\-/]*\.\w+)'
            r'[^\n]*\n'
            r'```(?:\w+)?\n(.*?)```',
            re.DOTALL,
        )
        for m in _fuzzy_re.finditer(peer_output):
            fname = os.path.basename(m.group(1))
            code = m.group(2)
            if not fname or not code or len(code.strip()) < 50:
                continue
            if not any(fname.endswith(ext) for ext in _CODE_EXTS):
                continue
            _safe_write(fname, code)

    # ── Fallback: bare fenced blocks — infer filename from context ────────────
    # Only runs when the primary pass wrote nothing.
    if not files_written:
        _expected_fname = None
        if context_message:
            _fname_re = re.compile(
                r'\b([\w][\w\-]*\.(?:py|js|ts|html|css|json))\b'
            )
            _m = _fname_re.search(context_message)
            if _m:
                _expected_fname = _m.group(1)

        if _expected_fname and any(_expected_fname.endswith(ext) for ext in _CODE_EXTS):
            _bare_re = re.compile(
                r'```(?:python|py|javascript|js|typescript|ts|html|css|json)?\n(.*?)```',
                re.DOTALL,
            )
            for m in _bare_re.finditer(peer_output):
                code = m.group(1)
                if not code or len(code.strip()) < 50:
                    continue
                if _safe_write(_expected_fname, code):
                    break  # first qualifying block only

    return files_written


def run_agent(user_message, history, yolo=False, use_plan=False, no_plan=False, _in_subtask=False, _plan_rag_block=""):
    # Reset streaming flag at start of each agent turn
    import core.inference_v2 as _inf_mod
    _inf_mod._last_was_streamed = False

    # Learn preferences from natural language in the user's message
    _get_learning().learn_from_message(user_message)

    # ── Explicit peer delegation ──────────────────────────────────────────────
    # Handle: "ask gemini to X", "have claude do X", etc.
    # The peer runs, its output is injected as context, then the agent applies it.
    if not _in_subtask:
        _peer_name, _peer_task = _detect_peer_delegation(user_message)
        if _peer_name and _peer_task:
            from core.peer_cli import get_peer_cli_manager
            _mgr = get_peer_cli_manager()
            _by_name = {c.name: c for c in _mgr.available()}
            if _peer_name in _by_name:
                _cli = _by_name[_peer_name]

                # For review/check/verify tasks, build rich context with current file contents
                # so the peer actually has something to review.
                _REVIEW_KW = {
                    "check", "review", "verify", "test", "examine",
                    "correct", "validate", "look at", "is it right", "did i"
                }
                _is_review = any(k in _peer_task.lower() for k in _REVIEW_KW)

                # ── Design-only phase detection ───────────────────────────────
                # When the peer is asked to "design / plan / spec / outline"
                # without any implement/build/code verb, we use prose instructions
                # and save the output as a .md design document instead of trying
                # to extract code blocks — which would corrupt the pipeline.
                _STRONG_DESIGN = re.compile(
                    r'\b(design|plan|spec(?:ify)?|specification|outline|blueprint|'
                    r'architecture|feature\s+list|roadmap|requirements?)\b',
                    re.IGNORECASE,
                )
                _STRONG_IMPLEMENT = re.compile(
                    r'\b(implement|build|code|develop|program|write\s+(?:code|it|the)|'
                    r'make\s+it\s+work|working\s+version)\b',
                    re.IGNORECASE,
                )
                _is_design_only = (
                    not _is_review  # review tasks always use code output format
                    and bool(_STRONG_DESIGN.search(_peer_task))
                    and not bool(_STRONG_IMPLEMENT.search(_peer_task))
                )

                # Output format instructions — Codey extracts code blocks to write files.
                # Claude -p returns plain text; without explicit format instructions it
                # asks for permission or returns prose instead of extractable code.
                _FORMAT_INSTRUCTIONS = (
                    "\n\nOUTPUT FORMAT (required — Codey will parse this automatically):\n"
                    "You are responding to an automated system. Do NOT ask for permission.\n"
                    "Do NOT ask clarifying questions. Act immediately.\n"
                    "For each file to create or modify, output it using this exact format:\n\n"
                    "**`filename.py`**\n"
                    "```python\n"
                    "# complete file content here\n"
                    "```\n\n"
                    "Use the correct language tag for non-Python files (javascript, json, etc.).\n"
                    "Write COMPLETE file content — no stubs, no placeholders, no '...'.\n"
                    "Codey will write these files to disk automatically."
                )
                # Design tasks: ask for prose, NOT code blocks.
                # Code blocks in design output are misinterpreted by _auto_apply_peer_code.
                _DESIGN_INSTRUCTIONS = (
                    "\n\nOUTPUT FORMAT:\n"
                    "You are responding to an automated system. Write a clear, detailed design "
                    "specification in prose and markdown.\n"
                    "Do NOT write any code. Do NOT include code blocks (no triple backticks).\n"
                    "For data structures or schemas, describe them in plain text or markdown "
                    "tables — NOT code blocks.\n"
                    "Describe: features, CLI commands and their arguments, data model, "
                    "behavior, edge cases, and any constraints.\n"
                    "Your output will be saved as a design document for another AI to implement from."
                )

                _enriched_task = (
                    f"Task: {_peer_task}"
                    + (_DESIGN_INSTRUCTIONS if _is_design_only else _FORMAT_INSTRUCTIONS)
                )

                # ── Multi-peer output passing ─────────────────────────────────
                # Only relevant for implementation steps that reference a prior peer's design.
                # Design steps (step 1 of a pipeline) never have a prior peer to inject.
                if not _is_design_only:
                    _OTHER_PEERS = [p for p in ["claude", "gemini", "qwen"] if p != _peer_name]
                    _referenced_peer = None
                    for _op in _OTHER_PEERS:
                        if _op in _peer_task.lower():
                            _referenced_peer = _op
                            break
                    # Also catch implicit references ("the previous design", "what was planned")
                    if not _referenced_peer:
                        _IMPLICIT_REF = re.compile(
                            r'\b(previous\s+(?:design|plan|output|step|result)|'
                            r'what\s+was\s+(?:designed|planned|created)|'
                            r'the\s+(?:design|plan|spec|feature\s+list)\s+(?:above|from\s+before|provided))\b',
                            re.IGNORECASE,
                        )
                        if _IMPLICIT_REF.search(_peer_task):
                            # Take the most recent peer output of any other peer
                            for _op in _OTHER_PEERS:
                                _candidate = _extract_peer_output_from_history(history, _op)
                                if _candidate:
                                    _referenced_peer = _op
                                    break
                    if _referenced_peer:
                        _prior_output = _extract_peer_output_from_history(history, _referenced_peer)
                        if _prior_output:
                            info(f"Injecting {_referenced_peer}'s previous output into {_peer_name}'s context")
                            _enriched_task = (
                                f"Task: {_peer_task}\n\n"
                                f"Context from {_referenced_peer.capitalize()}'s previous output "
                                f"(use this as your specification):\n\n"
                                f"{_prior_output}\n\n"
                                f"Your task: {_peer_task}"
                                + _FORMAT_INSTRUCTIONS
                            )

                if _is_review:
                    # Data-privacy gate: warn before sending local file contents
                    # to an external AI service. This is explicit and opt-in.
                    from utils.logger import warning as _priv_warn, confirm as _priv_confirm
                    _priv_warn(
                        f"Sending project files to {_peer_name} (external AI). "
                        "Local source code will leave this device."
                    )
                    _include_files = _priv_confirm(
                        f"Share local project file contents with {_peer_name}?"
                    )
                    if not _include_files:
                        # Use task only — no file contents sent externally
                        _is_review = False
                if _is_review:
                    from pathlib import Path as _PP
                    _file_parts = []
                    for _f in sorted(_PP.cwd().iterdir()):
                        if _f.is_file() and _f.suffix in ('.py', '.js', '.ts', '.txt', '.md', '.json'):
                            try:
                                _fc = _f.read_text(encoding='utf-8', errors='replace')
                                if len(_fc) < 4000:
                                    _file_parts.append(f"=== {_f.name} ===\n{_fc}")
                            except Exception:
                                pass
                    if _file_parts:
                        # Use the current user message as the task — do NOT override
                        # from history.  A resumed session may have old messages that
                        # would replace the current task with an unrelated one.
                        _orig_goal = user_message
                        _enriched_task = (
                            f"Task: {_orig_goal}\n\n"
                            "Current project files for context:\n\n"
                            + "\n\n".join(_file_parts[:6])
                            + f"\n\nYou must: {_peer_task}"
                            + _FORMAT_INSTRUCTIONS
                        )

                info(f"Delegating to {_cli.description}: {_peer_task[:80]}")
                _output = _mgr.call(_cli, _enriched_task)
                if _mgr.is_peer_error(_output):
                    warning(f"Peer '{_peer_name}' unavailable — falling back to local inference.")
                    # Fall through to normal agent inference below
                elif _output and len(_output.strip()) > 10:
                    _summary = _mgr.summarize_result(_cli.name, _output, _peer_task)
                    # Store peer exchange in history so context is preserved
                    history.append({"role": "user", "content": user_message})
                    history.append({"role": "assistant", "content": _summary})

                    # ── Design-only: save prose output to {peer}_design.md ────
                    # For design tasks we skip _auto_apply_peer_code entirely —
                    # code-block extraction would corrupt a markdown spec that
                    # contains data-structure examples in backtick blocks.
                    if _is_design_only:
                        import os as _os
                        _design_fname = f"{_peer_name}_design.md"
                        _design_path = _os.path.join(_os.getcwd(), _design_fname)
                        try:
                            with open(_design_path, "w", encoding="utf-8") as _dfile:
                                _dfile.write(_output)
                            success(f"Design saved to {_design_fname} ({len(_output)} chars)")
                        except Exception as _de:
                            warning(f"Could not save design file: {_de}")
                        # Plan will handle the next step (implement from design)
                        return _summary, history

                    # Auto-extract and write code blocks from peer output.
                    # The 7B local model struggles to parse large peer responses,
                    # so we extract ```python blocks with filenames and write them directly.
                    _files_written = _auto_apply_peer_code(_output, user_message)

                    if _files_written:
                        from utils.logger import success as _suc
                        _suc(f"[Peer: {_peer_name}] done. Applied {len(_files_written)} file(s): {', '.join(_files_written)}")
                        # Run tests if the peer provided test files AND the original task
                        # asked for them to be run.  Do this directly (no model inference)
                        # so the step cannot be skipped by a weak or confused model.
                        _has_tests = any('test' in f.lower() for f in _files_written)
                        _run_requested = any(k in user_message.lower() for k in [
                            "run", "show", "result", "execute", "test it",
                        ])
                        # When running as a plan step (no_plan=True), the plan itself
                        # has a dedicated "Run:" follow-up step — don't spawn another one.
                        if no_plan:
                            return _summary, history
                        if _has_tests and _run_requested:
                            _test_file = next(f for f in _files_written if 'test' in f.lower())
                            _cmd = f"python -m pytest {_test_file} -v"
                            info(f"Running tests: {_cmd}")
                            _test_result = shell(_cmd, yolo=yolo)
                            show_shell(_cmd, _test_result)
                            history.append({"role": "user", "content": f"Run: {_cmd}"})
                            history.append({"role": "assistant", "content": _test_result})
                            return _test_result, history
                        elif _has_tests:
                            # Tests written but not explicitly requested — ask model
                            _test_file = next(f for f in _files_written if 'test' in f.lower())
                            _follow_up = f"Run: python -m pytest {_test_file} -v"
                            return run_agent(_follow_up, history, yolo=yolo, _in_subtask=True)
                        else:
                            _follow_up = (
                                f"Original task: {user_message}\n\n"
                                f"Files written from peer review: {', '.join(_files_written)}. "
                                "Verify ALL requirements from the original task are met. "
                                "Summarize what was done in 2-3 sentences."
                            )
                            return run_agent(_follow_up, history, yolo=yolo, _in_subtask=True)
                    else:
                        # No code blocks found — fall back to asking agent to interpret
                        _follow_up = (
                            f"Original task: {user_message}\n\n"
                            f"The peer CLI {_peer_name} responded:\n\n"
                            f"{_output[:1500]}\n\n"
                            "Apply any code fixes the peer identified using write_file. "
                            "Then verify ALL requirements from the original task are met — "
                            "if anything is missing, implement it now. "
                            "Summarize what was done in 2-3 sentences."
                        )
                        from utils.logger import success as _suc
                        _suc(f"[Peer: {_peer_name}] done. Applying result...")
                        return run_agent(_follow_up, history, yolo=yolo, _in_subtask=True)
                else:
                    warning(f"Peer '{_peer_name}' returned no output. Continuing locally.")
            else:
                warning(
                    f"Peer '{_peer_name}' not available "
                    f"({', '.join(_by_name) or 'none installed'}). Continuing locally."
                )

    from prompts.layered_prompt import build_recursive_prompt
    used, total = get_context_usage([{"role": "system", "content": build_recursive_prompt("")}])
    if used < total * 0.5:
        auto_load_from_prompt(user_message)
    enriched = enrich_message(user_message)
    # Orchestrator — complex tasks get broken into subtask queue
    from core.orchestrator import is_complex, plan_tasks, run_queue
    from core.display import show_task_plan, console
    if is_complex(user_message) and not _in_subtask and not no_plan:
        info("Planning subtasks...")
        queue = plan_tasks(user_message, read_codeymd())
        if queue.tasks:
            show_task_plan(queue)
            try:
                ans = console.input("  Execute this plan? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("n", "no"):
                return "[Cancelled]", history
            run_queue(queue, yolo=yolo)
            _failed = [t for t in queue.tasks if t.status == 'failed']
            summary = f"Completed {queue.done_count()}/{len(queue.tasks)} tasks."
            if _failed:
                summary += " Failed: " + "; ".join(t.description[:50] for t in _failed) + "."
            history.append({"role": "user",     "content": user_message})
            history.append({"role": "assistant", "content": summary})
            return summary, history

    if use_plan:
        from core.planner import get_plan, show_and_confirm_plan
        info("Generating plan...")
        plan = get_plan(user_message, read_codeymd())
        approved, enriched = show_and_confirm_plan(plan)
        if not approved:
            return "[Cancelled]", history
    # Tick memory manager — evicts stale files, advances turn counter
    from core.memory_v2 import memory as _mem
    _mem.tick()
    # ── Phase 3: Layered system prompt (draft phase) ──────────────────────────
    sys_prompt = build_recursive_prompt(user_message, phase="draft", plan_rag_block=_plan_rag_block)
    messages = [{"role": "system", "content": sys_prompt}]

    # Adaptive context management — only compress when context > 75% of n_ctx
    # Build a temporary full messages array for accurate token measurement
    _tmp_msgs = messages + history + [{"role": "user", "content": user_message}]
    if should_summarize(history, system_messages=_tmp_msgs):
        history = summarize_history(history)
        # NOTE: _mem.compress_summary() was removed here — it calls infer()
        # on the same 7B model that's about to run the real task, causing
        # a single-slot collision. The 0.5B summarize_history() is sufficient.
    # Rebuild messages with potentially compressed history
    messages = [{"role": "system", "content": sys_prompt}]
    
    # Pre-inference guide: if it's a question or conversation, tell it NOT to use tools
    msg_low = user_message.lower().strip()
    _action_kws = [
        "create", "write", "make", "build", "edit", "fix", "run", "execute",
        "install", "add", "delete", "remove", "update", "patch", "refactor",
        "implement", "generate", "rewrite", "deploy", "setup", "configure",
        "review", "analyze", "analyse", "audit", "examine", "inspect", "assess",
        "read", "look at", "show me", "check",
        # Previously missing — caused QA false-positives for real edit requests:
        "replace", "rename", "swap", "convert", "change", "append", "insert",
        "move", "copy", "print", "output", "display", "open",
        # Memory triggers — should use note_save/note_forget tools:
        "remember", "don't forget", "forget",
        # Peer delegation triggers — "ask gemini to X" should never be QA:
        "ask gemini", "ask claude", "call gemini", "call claude",
        # Planner step verbs — daemon steps like "verify the output" must use shell,
        # not return plain text answers:
        "verify", "test", "validate", "confirm", "complete", "finish",
    ]
    _has_action = any(re.search(r'\b' + re.escape(k) + r'\b', msg_low) for k in _action_kws)
    _question_starters = (
        "what", "why", "how", "when", "where", "who", "which",
        "is ", "are ", "do ", "does ", "can ", "could ", "would ",
        "should ", "will ", "was ", "were ", "has ", "have ",
    )
    _qa_phrases = [
        "tell me", "tell me about", "explain", "help me understand",
        "what can you", "hello", "hi", "hey", "thanks", "thank you",
    ]
    is_qa = not _has_action and (
        msg_low.endswith("?") or
        msg_low.startswith(_question_starters) or
        any(re.search(r'\b' + re.escape(k) + r'\b', msg_low) for k in _qa_phrases)
    )
    if is_qa:
        messages.append({"role": "user", "content": "IMPORTANT: This is a question or conversation. Respond with plain text only. DO NOT use any tools. Keep your response concise — 2-3 sentences max unless more detail is needed."})

    keep = AGENT_CONFIG["history_turns"] * 2
    messages.extend(history[-keep:] if len(history) > keep else history)
    messages.append({"role": "user", "content": enriched})
    step = 0
    max_steps = AGENT_CONFIG["max_steps"]
    tools_used = []
    last_tool_result = ""
    duplicate_count = 0
    hallucination_count = 0
    auto_retries = 0
    max_retries = 1
    error_log = []        # accumulates error text for peer CLI context
    files_touched = []    # accumulates file paths for peer CLI context
    # Subtasks writing large files need more steps than simple Q&A.
    # If running inside the orchestrator (in_subtask) and the message contains
    # code-generation signals, raise the cap to 10.
    if _in_subtask:
        _complex_signals = ["overall goal", "write", "implement", "create", "build", "api", "server"]
        if any(s in user_message.lower() for s in _complex_signals):
            max_steps = max(max_steps, 10)

    while step < max_steps:
        step += 1
        used, total = get_context_usage(messages)
        pct = used / total if total > 0 else 0.0
        if pct > 0.85:
            warning("Context: " + usage_bar(used, total))
        else:
            info("Context: " + usage_bar(used, total))
        # ── Phase 2: Recursive inference on first step for non-QA tasks ─────────
        # Subsequent steps (reacting to tool results) use regular infer — recursion
        # is only valuable when generating the initial response/tool call.
        # Wrapped in try/except — recursive failure must never break the agent loop.
        _use_recursive = (
            step == 1
            and not is_qa
            and RECURSIVE_CONFIG.get("enabled", True)
        )
        _stop = ["</tool>"] + _LEAK_STOP_SEQUENCES
        _qa_max_tokens = 512 if is_qa else None
        if _use_recursive:
            try:
                from core.recursive import recursive_infer, classify_breadth_need
                _breadth = classify_breadth_need(user_message)
                if _breadth == "minimal":
                    response = infer(messages, stream=True,
                                     extra_stop=_stop, show_thinking=True,
                                     max_tokens=_qa_max_tokens)
                else:
                    _depth = 2 if _breadth == "deep" else 1
                    response = recursive_infer(
                        messages,
                        task_type="code",
                        user_message=user_message,
                        max_depth=_depth,
                        extra_stop=_stop,
                        stream=True,
                    )
            except Exception:
                # Recursive inference unavailable — fall back to plain infer
                response = infer(messages, stream=True,
                                 extra_stop=_stop, show_thinking=True,
                                 max_tokens=_qa_max_tokens)
        else:
            response = infer(messages, stream=True, extra_stop=_stop,
                             show_thinking=True, max_tokens=_qa_max_tokens)
        response = clean_response(response)
        tool_dict = parse_tool_call(response)

        # ── Malformed tool call: <tool> tag present but JSON failed to parse ──
        # The model tried to call a tool but emitted invalid JSON (e.g. missing
        # quote: {"name": patch_file"}).  Surface this as an explicit retry so
        # the model sees the error — without this it silently falls through to
        # the no-tool-call path and the step is skipped.
        if not tool_dict and "<tool>" in response and auto_retries < max_retries:
            auto_retries += 1
            warning("Malformed tool call — JSON parse failed, retrying")
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": (
                    "Your tool call had invalid JSON (e.g. a missing quote or bracket). "
                    "Fix the syntax and output ONLY a corrected <tool>...</tool> block.\n"
                    "Example: <tool>\n"
                    "{\"name\": \"write_file\", \"args\": {\"path\": \"x.py\", \"content\": \"code\"}}\n"
                    "</tool>"
                ),
            })
            continue

        # ── Recursive code-rescue: if recursive_infer produced good code as
        # prose (no tool call), extract the code block and synthesize write_file
        # directly — never ask the model again (prevents "YOUR CODE" placeholder).
        # Only fires on step 1 (_use_recursive), only for create-file requests,
        # only when a filename is present in the message and code is in the response.
        if not tool_dict and _use_recursive and not is_qa:
            _create_kws = ["create", "write", "make", "build", "generate", "implement"]
            if any(k in user_message.lower() for k in _create_kws):
                _fname_m = re.search(
                    r'\b([\w][\w\-]*\.(?:py|js|ts|html|css|json|sh|txt|md))\b',
                    user_message,
                )
                _code_m = re.search(
                    r'```(?:python|py|js|ts|bash|sh|json|html|css)?\n(.*?)```',
                    response, re.DOTALL,
                )
                if _fname_m and _code_m:
                    _extracted = _code_m.group(1).rstrip()
                    if len(_extracted) > 30:
                        tool_dict = {
                            "name": "write_file",
                            "args": {"path": _fname_m.group(1), "content": _extracted},
                        }

        if tool_dict:
            name = tool_dict.get("name", "")
            args = tool_dict.get("args", {})
            
            # SANITY CHECK: prevent hallucinated tool usage
            if is_qa and name not in ["read_file", "list_dir", "note_save", "note_forget"]:
                 warning(f"Model tried to use '{name}' for a general question.")
                 messages.append({"role": "assistant", "content": response})
                 messages.append({"role": "user", "content": "Just answer my question directly with text. No tools needed. Final answer format: 'I can help with [tasks].'"})
                 continue
            
            # Specific check for write/patch
            if name in ["write_file", "patch_file", "append_file"]:
                path = args.get("path", "")
                if path and path.lower() not in msg_low:
                    from pathlib import Path as _P
                    if not _P(path).exists() and not any(k in msg_low for k in ["create", "write", "new", "make"]):
                        # Exception: if we are retrying after a "No such file" shell
                        # error, the model is correctly trying to create the missing
                        # file — allow it through instead of blocking.
                        _missing_file_retry = (
                            auto_retries > 0
                            and "no such file" in last_tool_result.lower()
                        )
                        if not _missing_file_retry:
                            warning(f"Model tried to create/edit unexpected file: {path}")
                            messages.append({"role": "assistant", "content": response})
                            messages.append({"role": "user", "content": f"I didn't ask to modify '{path}'. Please answer my question directly."})
                            continue

            sig = name + ":" + json.dumps(args, sort_keys=True)
            if sig in tools_used:
                duplicate_count += 1
                if duplicate_count >= 2:
                    separator()
                    summary = "Done. " + last_tool_result[:300]
                    print("\033[1;32mCodey:\033[0m " + summary)
                    separator()
                    history.append({"role": "user",     "content": user_message})
                    history.append({"role": "assistant", "content": summary})
                    return summary, history
                messages.append({"role": "assistant", "content": _format_tool_for_history(tool_dict)})
                messages.append({"role": "user", "content": "Already ran that. Result: " + last_tool_result[:200] + "\nTask complete. Reply with 1 sentence only."})
                continue
            tools_used.append(sig)
            last_tool_result = execute_tool(tool_dict)
            if name in ("write_file", "patch_file"):
                from core.memory_v2 import memory as _mem
                fpath = args.get("path", "")
                # Load into working memory directly from args — avoids re-reading
                # from disk (the content is already in args["content"]).
                _wcontent = args.get("content", "") or args.get("new_str", "")
                if _wcontent and fpath:
                    _mem.load_file(fpath, _wcontent)
                _mem.touch_file(fpath)
                # Learn preferences (single call — removed duplicate from execute_tool)
                if fpath.endswith(".py") and _wcontent:
                    try:
                        _get_learning().learn_from_file(fpath, _wcontent)
                    except Exception:
                        pass
                del _wcontent  # release content ref
            elif name == "read_file":
                fpath = args.get("path", "")
                if fpath.endswith(".py") and not last_tool_result.startswith("[ERROR]"):
                    try:
                        _get_learning().learn_from_file(fpath, last_tool_result)
                    except Exception:
                        pass
            if is_error(last_tool_result, name):
                error_log.append(last_tool_result[:300])
            fpath_touched = args.get("path", "")
            if fpath_touched and fpath_touched not in files_touched:
                files_touched.append(fpath_touched)

            if is_error(last_tool_result, name) and auto_retries < max_retries:
                auto_retries += 1
                warning("Error detected — auto-retry " + str(auto_retries) + "/" + str(max_retries))
                messages.append({"role": "assistant", "content": _format_tool_for_history(tool_dict)})
                # If the user cancelled the command (declined confirmation), suggest
                # write_file as an alternative when the task is about creating a file.
                if name == "shell" and "[CANCELLED]" in last_tool_result:
                    _file_words = ["create", "write", "make", "build", "file", ".py", ".js", ".html", ".txt", ".md"]
                    if any(w in msg_low for w in _file_words):
                        messages.append({"role": "user", "content": "Command was not run. Use the write_file tool instead to create the file. Output ONLY a <tool> block with write_file."})
                        continue
                # FIX 3: argparse / usage errors mean the command was called wrong,
                # not that the source code is broken.  Tell the model to re-run with
                # correct arguments instead of patching working files.
                if name == "shell":
                    _res_low = last_tool_result.lower()
                    _USAGE_SIGNALS = [
                        "usage:",
                        "error: the following arguments are required",
                        "unrecognized arguments",
                    ]
                    if any(sig in _res_low for sig in _USAGE_SIGNALS):
                        messages.append({
                            "role": "user",
                            "content": (
                                "The command failed because it was called incorrectly. "
                                "Run it again with the correct arguments based on the original task. "
                                "Do not modify any files."
                            ),
                        })
                        continue
                messages.append({"role": "user", "content": "Error:\n" + last_tool_result[:400] + "\n\nFix the error and try again."})
                continue
            elif is_error(last_tool_result, name) and auto_retries >= max_retries and not _in_subtask:
                # Exhausted retries — offer to escalate to a peer CLI
                from core.peer_cli import escalate
                peer_result = escalate(user_message, error_log, files_touched)
                if peer_result and peer_result.startswith("[redirect]:"):
                    # User told Codey to try a different approach
                    new_instruction = peer_result[len("[redirect]: "):]
                    messages.append({"role": "user", "content": new_instruction})
                    auto_retries = 0
                    continue
                elif peer_result:
                    # Peer CLI ran — inject its output and let Codey act on it
                    messages.append({"role": "assistant", "content": _format_tool_for_history(tool_dict)})
                    messages.append({"role": "user", "content": peer_result + "\n\nBased on the above, complete the task or summarize what was accomplished."})
                    auto_retries = 0
                    continue
                # else: user skipped escalation, fall through to normal handling
            messages.append({"role": "assistant", "content": _format_tool_for_history(tool_dict)})
            # After write_file for a simple create request — force exit the loop.
            # The 7B model ignores "don't run commands" instructions and keeps
            # calling read_file/shell, so we must hard-stop here.
            if name == "write_file" and not any(k in user_message.lower() for k in ["run", "execute", "test", "start", "launch"]):
                _written_path = args.get("path", "the file")
                # Exception: for bug-fix requests with existing test files, inject a test run
                # instead of returning early — ensures fixes are actually verified.
                _is_fix = any(k in user_message.lower() for k in ["fix", "bug", "patch", "correct", "repair", "debug"])
                if _is_fix:
                    from pathlib import Path as _Path
                    _test_candidates = (
                        list(_Path.cwd().glob("test_*.py")) +
                        list(_Path.cwd().glob("*_test.py"))
                    )
                    if _test_candidates:
                        _tf = _test_candidates[0].name
                        _tf_mod = _test_candidates[0].stem
                        messages.append({"role": "user", "content": (
                            f"Tool result: {last_tool_result[:300]}\n"
                            f"Fixed {_written_path}. Now run the tests to verify the fix:\n"
                            f"python -m pytest {_tf} -v 2>&1 || python -m unittest {_tf_mod} -v 2>&1"
                        )})
                        auto_retries = 0
                        continue
                _confirm = f"Created {_written_path}"
                separator()
                print("\033[1;32mCodey:\033[0m " + _confirm)
                separator()
                history.append({"role": "user",      "content": user_message})
                history.append({"role": "assistant",  "content": _confirm})
                return _confirm, history
            else:
                # 2000 chars gives the model enough content to work with.
                # patch_file [PATCH_FAILED] responses include file content that
                # the model needs to reconstruct a correct write_file call.
                messages.append({"role": "user", "content": "Tool result: " + last_tool_result[:2000] + "\nNext action or final answer:"})
            continue
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        if (false_file or false_run) and hallucination_count == 0:
            hallucination_count += 1
            missing = []
            if false_file: missing.append("write_file")
            if false_run:  missing.append("shell")
            fname_match = re.search(r"(\w+\.py)", user_message)
            fname = fname_match.group(1) if fname_match else "output.py"
            tool_hint = '<tool>\n{"name": "write_file", "args": {"path": "' + fname + '", "content": "YOUR CODE"}}\n</tool>'
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": "You must call " + " and ".join(missing) + ".\nOutput ONLY a tool call:\n" + tool_hint})
            continue
        history.append({"role": "user",     "content": user_message})
        history.append({"role": "assistant", "content": response})
        if not _in_subtask:
            check_git_and_offer_commit(user_message, tools_used)
        return response, history
    warning("Reached max steps (" + str(max_steps) + ").")
    if not _in_subtask:
        check_git_and_offer_commit(user_message, tools_used)
    # Return a failure marker so run_queue() can flag this subtask as incomplete
    # instead of silently marking it done. The last tool result is included so
    # the next subtask knows what was attempted.
    _incomplete_msg = "[INCOMPLETE] Max steps reached."
    if last_tool_result and not last_tool_result.startswith("["):
        _incomplete_msg += " Last result: " + last_tool_result[:200]
    return _incomplete_msg, history
