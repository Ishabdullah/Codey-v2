import json
import re
from core.inference_v2 import infer
from core.context import build_file_context_block, auto_load_from_prompt, list_loaded
from core.project import get_project_summary
from core.codeymd import read_codeymd, find_codeymd
from core.summarizer import should_summarize, summarize_history
from core.tokens import get_context_usage, usage_bar
from prompts.system_prompt import SYSTEM_PROMPT
from tools.file_tools import tool_read_file, tool_write_file, tool_append_file, tool_list_dir
from tools.patch_tools import tool_patch_file
from tools.shell_tools import shell, search_files
from utils.logger import tool_call, tool_result, warning, separator, info
from utils.config import AGENT_CONFIG
from core.display import show_file_write, show_patch, show_shell, show_tool_generic, show_response

TOOLS = {
    "read_file":    lambda args: tool_read_file(args["path"]),
    "write_file":   lambda args: tool_write_file(args["path"], args["content"]),
    "patch_file":   lambda args: tool_patch_file(args["path"], args["old_str"], args["new_str"]),
    "append_file":  lambda args: tool_append_file(args["path"], args["content"]),
    "list_dir":     lambda args: tool_list_dir(args.get("path", ".")),
    "shell":        lambda args: shell(args["command"]),
    "search_files": lambda args: search_files(args["pattern"], args.get("path", ".")),
}
ROGUE_TAG_MAP = {
    "write_file": "write_file", "read_file": "read_file",
    "patch_file": "patch_file", "shell": "shell",
    "append_file": "append_file", "list_dir": "list_dir",
    "search_files": "search_files",
}

HALLUCINATION_MARKERS = [
    "\nuser\n", "\nUSER\n", "\nUser\n",
    "\nassistant\n", "\nASSISTANT\n", "\nAssistant\n",
    "user\n#", "assistant\n", "user\ncreate", "user\nwrite", "user\nedit", "user\nrun",
    "\n## Loaded Files", "\n## Project Memory", "\n## Current Project",
    "## Project Memory\n", "## Loaded Files\n",
    "## Loaded Files", "## Project Memory",
    "<|im_start|>", "<|im_end|>",
]

def clean_response(text):
    for marker in HALLUCINATION_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
    return text.strip()

def extract_json(raw):
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

    # Try raw candidate first, then cleaned version
    for s in [candidate, cleaned]:
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            pass

    # Final fallback: manual regex extraction for known keys
    result = {}
    for key in ["name", "path", "content", "command", "pattern", "old_str", "new_str"]:
        m = re.search('"' + key + '"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"', candidate, re.DOTALL)
        if not m:
             # Try without re.DOTALL if it failed, maybe it's multi-line without escaping
             m = re.search('"' + key + '"\\s*:\\s*"(.*?)"', candidate, re.DOTALL)
        if m:
            result[key] = m.group(1).replace('\\n', '\n').replace('\\"', '"')
            continue
    
    if result:
        name = result.pop("name", None)
        if name:
            return {"name": name, "args": result}
        return result
    return None

def parse_tool_call(text):
    match = re.search(r"<tool>\s*(\{.*)", text, re.DOTALL)
    if match:
        result = extract_json(match.group(1))
        if result and "name" in result:
            return result
    for tag, canonical in ROGUE_TAG_MAP.items():
        match = re.search(r"<" + tag + r">\s*(\{.*)", text, re.DOTALL)
        if match:
            inner = extract_json(match.group(1))
            if inner:
                if "name" in inner:
                    return inner
                return {"name": canonical, "args": inner}
    return None

def execute_tool(tool_dict):
    name = tool_dict.get("name", "")
    args = tool_dict.get("args", {})
    if name not in TOOLS:
        return "[ERROR] Unknown tool: " + name
    try:
        # Get old content before write for diff display
        old_content = None
        if name == "write_file":
            from pathlib import Path as _P
            p = _P(args.get("path", ""))
            if p.exists():
                try: old_content = p.read_text()
                except: pass
        result = TOOLS[name](args)
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
        return "[ERROR] " + str(e)

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
    msg_lower = user_message.lower()
    resp_lower = response.lower()
    needs_file = any(k in msg_lower for k in [
        "create", "write", "make", "build", "implement", "add", "generate",
    ])
    needs_run  = any(k in msg_lower for k in ["run", "execute", "test"])
    file_done  = any("write_file" in s or "patch_file" in s for s in tools_used)
    shell_done = any("shell" in s for s in tools_used)
    false_file = needs_file and not file_done and any(p in resp_lower for p in [
        "has been created", "was created", "have created",
        "successfully created", "file has been", "has been written", "created the file",
        "is already implemented", "already implemented", "capability is already",
        "already exists", "is implemented in",
    ])
    false_run = needs_run and not shell_done and any(p in resp_lower for p in [
        "run successfully", "executed successfully", "created and run", "ran successfully",
    ])
    return false_file, false_run

def build_system_prompt(message=""):
    parts = [SYSTEM_PROMPT]
    codeymd = read_codeymd()
    if codeymd:
        parts.append("\n## Project Memory\n" + codeymd)
    else:
        proj = get_project_summary()
        if proj:
            parts.append("\n## Current Project\n" + proj)
            
    from core.project import get_repo_map
    repo_map = get_repo_map()
    if repo_map:
        parts.append("\n" + repo_map)

    # Memory-aware: only inject files relevant to current message
    file_ctx = build_file_context_block(message)
    if file_ctx:
        parts.append("\n## Loaded Files\n" + file_ctx)
    return "\n".join(parts)

def enrich_message(user_message):
    loaded = list_loaded()
    if not loaded:
        return user_message
    fix_keywords = ["fix", "correct", "bug", "wrong", "error", "broken",
                    "update", "change", "edit", "modify", "patch"]
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

def run_agent(user_message, history, yolo=False, use_plan=False, no_plan=False, _in_subtask=False):
    used, total = get_context_usage([{"role": "system", "content": build_system_prompt()}])
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
    # Compress/summarize history — use only one path per call to avoid double inference
    if len(history) >= 8:
        history = _mem.compress_summary(history)
        # Trim to keep only the summary + recent turns in memory
        keep = AGENT_CONFIG["history_turns"] * 2
        if len(history) > keep:
            history = history[-keep:]
    elif should_summarize(history):
        history = summarize_history(history)
    sys_prompt = build_system_prompt(user_message)
    messages = [{"role": "system", "content": sys_prompt}]
    
    # Pre-inference guide: if it's a question or conversation, tell it NOT to use tools
    msg_low = user_message.lower().strip()
    _action_kws = [
        "create", "write", "make", "build", "edit", "fix", "run", "execute",
        "install", "add", "delete", "remove", "update", "patch", "refactor",
        "implement", "generate", "rewrite", "deploy", "setup", "configure",
    ]
    _has_action = any(k in msg_low for k in _action_kws)
    _question_starters = (
        "what", "why", "how", "when", "where", "who", "which",
        "is ", "are ", "do ", "does ", "can ", "could ", "would ",
        "should ", "will ", "was ", "were ", "has ", "have ",
    )
    _qa_phrases = [
        "tell me", "tell me about", "explain", "help me understand",
        "what can you", "hello", "hi ", "hey ", "thanks", "thank you",
    ]
    is_qa = not _has_action and (
        msg_low.endswith("?") or
        msg_low.startswith(_question_starters) or
        any(k in msg_low for k in _qa_phrases)
    )
    if is_qa:
        messages.append({"role": "user", "content": "IMPORTANT: This is a question or conversation. Respond with plain text only. DO NOT use any tools."})

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
    max_retries = 2
    while step < max_steps:
        step += 1
        used, total = get_context_usage(messages)
        pct = used / total
        if pct > 0.85:
            warning("Context: " + usage_bar(used, total))
        else:
            info("Context: " + usage_bar(used, total))
        response = infer(messages, stream=True, extra_stop=["</tool>"], show_thinking=True)
        response = clean_response(response)
        tool_dict = parse_tool_call(response)
        if tool_dict:
            name = tool_dict.get("name", "")
            args = tool_dict.get("args", {})
            
            # SANITY CHECK: prevent hallucinated tool usage
            if is_qa and name not in ["read_file", "list_dir"]:
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
                messages.append({"role": "assistant", "content": "<tool>\n" + json.dumps(tool_dict) + "\n</tool>"})
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
            if is_error(last_tool_result, name) and auto_retries < max_retries:
                auto_retries += 1
                warning("Error detected — auto-retry " + str(auto_retries) + "/" + str(max_retries))
                messages.append({"role": "assistant", "content": "<tool>\n" + json.dumps(tool_dict) + "\n</tool>"})
                messages.append({"role": "user", "content": "Error:\n" + last_tool_result + "\n\nFix the implementation file only. Never modify test files. After fixing, run the tests again to verify."})
                continue
            messages.append({"role": "assistant", "content": "<tool>\n" + json.dumps(tool_dict) + "\n</tool>"})
            messages.append({"role": "user", "content": "Tool result: " + last_tool_result[:500] + "\nNext action or final answer:"})
            continue
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        if false_file or false_run:
            hallucination_count += 1
            missing = []
            if false_file: missing.append("write_file")
            if false_run:  missing.append("shell")
            if hallucination_count >= 3:
                warning("Model repeatedly hallucinated. Try rephrasing your request.")
                separator()
                history.append({"role": "user",     "content": user_message})
                history.append({"role": "assistant", "content": response})
                return response, history
            fname_match = re.search(r"(\w+\.py)", user_message)
            fname = fname_match.group(1) if fname_match else "output.py"
            tool_hint = '<tool>\n{"name": "write_file", "args": {"path": "' + fname + '", "content": "YOUR CODE"}}\n</tool>'
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": "The file does not exist. You must call " + " and ".join(missing) + ".\nOutput ONLY a tool call:\n" + tool_hint})
            continue
        separator()
        history.append({"role": "user",     "content": user_message})
        history.append({"role": "assistant", "content": response})
        if not _in_subtask:
            check_git_and_offer_commit(user_message, tools_used)
        return response, history
    warning("Reached max steps (" + str(max_steps) + ").")
    if not _in_subtask:
        check_git_and_offer_commit(user_message, tools_used)
    return "[Max steps reached]", history
