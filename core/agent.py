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
from prompts.system_prompt import SYSTEM_PROMPT
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
    "shell":        lambda args: shell(args["command"]),
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
    # System-prompt echo — model regurgitating its own context
    "\n## Loaded Files", "\n## Project Memory", "\n## Current Project",
    "\n## User Notes", "\n## Project Map", "\n## User Preferences",
    "\n## Relevant Skills", "\n## Reference Material", "\n## Repo Map",
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
    braces, and literal newlines inside strings.
    """
    raw = raw.strip()
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

    # Try raw candidate first, then cleaned, then newline-fixed
    for s in [candidate, cleaned, _fix_literal_newlines(cleaned)]:
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
        # Get old content before write for diff display
        old_content = None
        if name == "write_file":
            from pathlib import Path as _P
            p = _P(args.get("path", ""))
            if p.exists():
                try: old_content = p.read_text()
                except: pass
        
        # ── Pre-write syntax check (Phase 2) ────────────────────────────────
        # Check syntax but STILL WRITE the file. Blocking writes entirely
        # creates a death spiral where the 7B model retries with less context
        # and produces even worse code. Better to write it and report the error.
        _syntax_warning = ""
        if name == "write_file":
            _wpath = args.get("path", "")
            _wcontent = args.get("content", "")
            if _wpath.endswith(".py") and _wcontent:
                try:
                    from core.linter import check_syntax
                    _syn_err = check_syntax(_wcontent, _wpath)
                    if _syn_err:
                        _syntax_warning = f"\n[WARNING] Syntax issue: {_syn_err}"
                except Exception:
                    pass

        result = TOOLS[name](args)
        if _syntax_warning and not result.startswith("[ERROR]"):
            result += _syntax_warning
        duration = time.time() - start_time

        # ── Auto-lint after successful Python file write (Phase 2) ───────────
        # Only inject ERRORS into agent context (causes agent to self-correct).
        # Style warnings are shown to the user in the terminal but NOT injected
        # — otherwise the agent loops trying to fix unused-import noise etc.
        if name in ("write_file", "patch_file") and not result.startswith("[ERROR]"):
            _lpath = args.get("path", "")
            if _lpath.endswith(".py"):
                try:
                    from core.linter import run_linter, format_issues
                    _issues, _linter_used = run_linter(_lpath)
                    if _issues:
                        _errors   = [i for i in _issues if i.severity == "error"]
                        _warnings = [i for i in _issues if i.severity != "error"]
                        # Inject errors so the agent fixes them in the next step
                        if _errors:
                            result += format_issues(_errors)
                        # Show warnings to the user without pressuring the agent
                        if _warnings:
                            from utils.logger import warning as _lwarn
                            _lwarn(f"[Linter/{_linter_used}] {len(_warnings)} style warning(s) in {_lpath}:")
                            for _w in _warnings[:5]:
                                _lwarn(f"  Line {_w.line}: [{_w.code}] {_w.message}")
                            if len(_warnings) > 5:
                                _lwarn(f"  ... and {len(_warnings) - 5} more (run /review for full list)")
                except Exception:
                    pass  # linter unavailable — continue normally

        # Learn from successful file operations
        if name in ("write_file", "patch_file") and not result.startswith("[ERROR]"):
            # Learn preferences from generated content
            content = args.get("content", "")
            path = args.get("path", "")
            if content and path:
                learning.learn_from_file(path, content)
        
        # Display using Claude Code style panels
        if name == "write_file":
            show_file_write(args.get("path",""), args.get("content",""), old_content)
        elif name == "patch_file":
            show_patch(args.get("path",""), args.get("old_str",""), args.get("new_str",""))
        elif name == "shell":
            is_err = is_error(result, "shell")
            show_shell(args.get("command",""), result, error=is_err)
        elif name != "read_file":
            show_tool_generic(name, args, result)
        
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
    return None, None


def _auto_apply_peer_code(peer_output):
    """
    Extract code blocks from peer CLI output and write them to disk.

    Looks for patterns like:
      **`app.py`** — description
      ```python
      code...
      ```

    Or:
      **app.py**
      ```python
      code...
      ```

    Returns list of filenames written, or empty list if none found.
    """
    import os
    files_written = []

    # Pattern: filename header followed by a code block
    # Matches: **`filename.py`** or **filename.py** or `filename.py`:
    _block_re = re.compile(
        r'(?:\*{1,2}`?(\w+\.\w+)`?\*{0,2}|`(\w+\.\w+)`:?)\s*(?:—[^\n]*)?\s*\n'
        r'```(?:\w+)?\n(.*?)```',
        re.DOTALL
    )

    for m in _block_re.finditer(peer_output):
        fname = m.group(1) or m.group(2)
        code = m.group(3)
        if not fname or not code or len(code.strip()) < 50:
            continue
        # Only write code files
        if not any(fname.endswith(ext) for ext in ('.py', '.js', '.ts', '.html', '.css', '.json')):
            continue
        # Syntax check for Python files
        if fname.endswith('.py'):
            try:
                from core.linter import check_syntax
                if check_syntax(code.rstrip(), fname):
                    continue  # Skip files with syntax errors
            except Exception:
                pass
        # Write the file
        fpath = os.path.join(os.getcwd(), fname)
        try:
            from pathlib import Path as _WP
            _WP(fpath).write_text(code.rstrip() + '\n', encoding='utf-8')
            files_written.append(fname)
            success(f"Written {fname} from peer review ({len(code)} chars)")
        except Exception as e:
            warning(f"Failed to write {fname} from peer: {e}")

    return files_written


def run_agent(user_message, history, yolo=False, use_plan=False, no_plan=False, _in_subtask=False):
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
                _enriched_task = _peer_task
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
                        # Find the original goal from history or current message
                        _orig_goal = user_message
                        for _hm in reversed(history):
                            if _hm["role"] == "user" and len(_hm["content"]) > 80:
                                _orig_goal = _hm["content"][:800]
                                break
                        _enriched_task = (
                            f"Original task that was worked on:\n{_orig_goal}\n\n"
                            "Current state of project files:\n\n"
                            + "\n\n".join(_file_parts[:6])
                            + f"\n\nPlease: {_peer_task}"
                        )

                info(f"Delegating to {_cli.description}: {_peer_task[:80]}")
                _output = _mgr.call(_cli, _enriched_task)
                if _output and len(_output.strip()) > 10:
                    _summary = _mgr.summarize_result(_cli.name, _output, _peer_task)
                    # Store peer exchange in history so context is preserved
                    history.append({"role": "user", "content": user_message})
                    history.append({"role": "assistant", "content": _summary})

                    # Auto-extract and write code blocks from peer output.
                    # The 7B local model struggles to parse large peer responses,
                    # so we extract ```python blocks with filenames and write them directly.
                    _files_written = _auto_apply_peer_code(_output)

                    if _files_written:
                        from utils.logger import success as _suc
                        _suc(f"[Peer: {_peer_name}] done. Applied {len(_files_written)} file(s): {', '.join(_files_written)}")
                        # Run tests if the peer provided test files
                        _has_tests = any('test' in f.lower() for f in _files_written)
                        if _has_tests:
                            _follow_up = (
                                f"Files written from peer review: {', '.join(_files_written)}. "
                                "Run the tests now with: python -m unittest test_api"
                            )
                        else:
                            _follow_up = (
                                f"Files written from peer review: {', '.join(_files_written)}. "
                                "Summarize what was fixed in 2-3 sentences."
                            )
                        return run_agent(_follow_up, history, yolo=yolo, _in_subtask=True)
                    else:
                        # No code blocks found — fall back to asking agent to interpret
                        _follow_up = (
                            f"The peer CLI {_peer_name} responded:\n\n"
                            f"{_output[:1500]}\n\n"
                            "If the peer identified bugs or gave code fixes, apply them now "
                            "using write_file. Otherwise, summarize findings in 2-3 sentences."
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
        if len(queue.tasks) > 1:
            show_task_plan(queue)
            try:
                ans = console.input("  Execute this plan? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("n", "no"):
                return "[Cancelled]", history
            run_queue(queue, yolo=yolo)
            summary = "Completed " + str(queue.done_count()) + "/" + str(len(queue.tasks)) + " tasks."
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
    from core.memory import memory as _mem
    _mem.tick()
    # ── Phase 3: Layered system prompt (draft phase) ──────────────────────────
    sys_prompt = build_recursive_prompt(user_message, phase="draft")
    messages = [{"role": "system", "content": sys_prompt}]

    # Adaptive context management — only compress when context > 75% of n_ctx
    # Build a temporary full messages array for accurate token measurement
    _tmp_msgs = messages + history + [{"role": "user", "content": user_message}]
    if should_summarize(history, system_messages=_tmp_msgs):
        history = summarize_history(history)
        # Also try memory manager compression for file context
        if len(history) >= 8:
            history = _mem.compress_summary(history)
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
        pct = used / total
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
                from core.context import load_file
                from core.memory import memory as _mem
                fpath = args.get("path", "")
                load_file(fpath)
                _mem.touch_file(fpath)
                if fpath.endswith(".py"):
                    try:
                        from pathlib import Path as _P
                        _content = _P(fpath).read_text(encoding="utf-8", errors="replace")
                        _get_learning().learn_from_file(fpath, _content)
                    except Exception:
                        pass
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
            messages.append({"role": "user", "content": "Tool result: " + last_tool_result[:500] + "\nNext action or final answer:"})
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
