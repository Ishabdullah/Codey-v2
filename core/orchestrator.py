"""
Orchestrator — plans complex tasks into subtask queues and executes them.
"""
import re
from pathlib import Path
from core.taskqueue import TaskQueue, STATUS_PENDING, STATUS_RUNNING
from utils.logger import info, warning

from prompts.system_prompt import GUIDANCE_HTTP_SERVER, GUIDANCE_HTTP_TESTING, GUIDANCE_SQLITE, GUIDANCE_PERSISTENCE

PLAN_PROMPT = """Break the task into 2-5 numbered steps. Max 5 steps.
Each step must be a single concrete action: create a file, edit a file, or run a command.
Each step is ONE short sentence describing WHAT to do. Do NOT write any code in the plan.
NEVER include "open", "save", or "navigate" steps (too vague).
Running tests (e.g. "run pytest") and committing code (e.g. "git commit") ARE valid steps.
If the user asks to run the script, add/insert records, or prove/demonstrate functionality, include EACH of those as a separate numbered step with the shell command to run.
NEVER create .db files (sqlite3.connect() creates them automatically).
NEVER use port 8080 (reserved). Use 8765 or 9000.
Output ONLY the numbered list."""

COMPLEX_SIGNALS = [
    'create', 'build', 'implement', 'refactor', 'rewrite',
    'add', 'and then', 'then run', 'also', 'multiple',
    'class', 'module', 'app', 'application', 'system', 'api',
    'with tests', 'and test', 'and run',
]

# Conversational patterns that should NOT trigger orchestration
CONVERSATIONAL_PATTERNS = [
    "how do i", "what is", "can you explain", "tell me about",
    "what's the best way", "should i use", "difference between",
    "explain how", "what does", "how does", "why does",
    "can you help me", "could you explain", "i need help",
    "what's the difference", "how to use", "how do you",
]

def is_complex(message):
    """
    Heuristic: does this need multiple steps?
    
    Uses keyword matching, conversational pattern detection, and message length
    to determine if a request should trigger orchestration.
    
    Args:
        message: User's request text
        
    Returns:
        True if request should be orchestrated, False otherwise
    """
    msg = message.lower()

    # Action keywords that indicate a task (not a question)
    # Keep in sync with _action_kws in core/agent.py
    _action_kws = [
        "create", "write", "make", "build", "edit", "fix", "run", "execute",
        "install", "add", "delete", "remove", "update", "patch", "refactor",
        "implement", "generate", "rewrite", "deploy", "setup", "configure",
        "review", "analyze", "analyse", "audit", "examine", "inspect", "assess",
        "read", "look at", "show me", "check",
        "replace", "rename", "swap", "convert", "change", "append", "insert",
        "move", "copy", "print", "output", "display", "open",
        "remember", "don't forget", "forget",
        "ask gemini", "ask claude", "call gemini", "call claude",
    ]
    _has_action = any(re.search(r'\b' + re.escape(k) + r'\b', msg) for k in _action_kws)

    # Question starters that indicate Q&A (not a task)
    _question_starters = (
        "what", "why", "how", "when", "where", "who", "which",
        "is ", "are ", "do ", "does ", "can ", "could ", "would ",
        "should ", "will ", "was ", "were ", "has ", "have ",
    )
    _qa_phrases = [
        "tell me", "tell me about", "explain", "help me understand",
        "what can you", "hello", "hi", "hey", "thanks", "thank you",
    ]

    # If no action keyword AND looks like a question, NOT complex
    if not _has_action and (
        msg.endswith("?") or
        msg.startswith(_question_starters) or
        any(re.search(r'\b' + re.escape(k) + r'\b', msg) for k in _qa_phrases)
    ):
        return False
    
    # Check for conversational patterns (even with action keywords)
    if any(pattern in msg for pattern in CONVERSATIONAL_PATTERNS):
        return False
    
    # Short messages are rarely complex
    if len(message) < 50:
        return False

    # Count positive signals
    signals = sum(1 for s in COMPLEX_SIGNALS if s in msg)

    # Scale threshold by message length
    # Longer messages need fewer signals to be considered complex
    if len(message) > 300:
        return signals >= 2
    elif len(message) > 150:
        return signals >= 2
    else:
        return signals >= 3

def parse_task_list(model_output):
    """Extract numbered steps from model output."""
    tasks = []
    for line in model_output.splitlines():
        line = line.strip()
        m = re.match(r'^(\d+)[.)\s]+(.+)$', line)
        if m and len(m.group(2)) > 5:
            tasks.append(m.group(2).strip())
    return _postprocess_plan(tasks[:5])


# Filename extraction pattern
_FILE_RE = re.compile(r'\b([\w][\w\-]*\.(?:py|js|ts|html|css|json|yaml|yml|toml|txt|md|sh))\b')


def _postprocess_plan(tasks):
    """
    Post-process plan steps: merge same-file steps and cap count.

    Recursive planning (Phase 4) self-corrects waste steps and quality,
    so this only handles structural deduplication.
    """
    if not tasks:
        return tasks

    # Merge steps targeting the same file — keep the longer description
    merged = []
    seen_files = {}  # filename -> index in merged list
    for t in tasks:
        files_in_step = _FILE_RE.findall(t)
        merged_into = None
        for f in files_in_step:
            if f in seen_files:
                merged_into = seen_files[f]
                break
        if merged_into is not None:
            if len(t) > len(merged[merged_into]):
                merged[merged_into] = t
        else:
            idx = len(merged)
            merged.append(t)
            for f in files_in_step:
                seen_files[f] = idx

    return merged[:5]

def plan_tasks(user_message, project_context=''):
    """
    Ask model to plan the task. Returns TaskQueue.

    Phase 4 (v2.6.4): Planning now uses recursive_infer() so the plan goes
    through one self-critique + refine cycle, and KB docs are retrieved and
    injected so the model plans with relevant API/pattern context.
    Falls back to plain infer() if anything goes wrong.
    """
    plan_prompt = PLAN_PROMPT
    if project_context:
        plan_prompt += f'\nProject context:\n{project_context}'
    # Inject git-repo awareness so model never adds "git init / .gitignore" steps
    try:
        from core.githelper import is_git_repo
        if is_git_repo():
            plan_prompt += (
                '\nIMPORTANT: Already inside an existing git repository. '
                'Do NOT add git init, .gitignore creation, or initial commit steps.'
            )
    except Exception:
        pass

    # ── Phase 4: Retrieve KB docs relevant to the planning request ────────────
    # Injected before the task description so the model plans with known patterns.
    retrieved_block = ""
    try:
        from core.retrieval import retrieve
        from utils.config import RETRIEVAL_CONFIG
        if RETRIEVAL_CONFIG.get("enabled", True):
            _retrieved = retrieve(user_message, budget_chars=1200)
            if _retrieved:
                retrieved_block = _retrieved + "\n\n"
    except Exception:
        pass  # KB unavailable — plan without retrieval

    messages = [
        {
            'role': 'user',
            'content': (
                plan_prompt
                + '\n\n'
                + retrieved_block
                + 'Task: ' + user_message
                + '\n\nNumbered steps:'
            ),
        }
    ]

    # ── Phase 4: Use recursive_infer for self-critiquing plan quality ─────────
    # task_type="plan" selects CRITIQUE_PLAN so critique checks step count,
    # order, redundancy, and completeness rather than code correctness.
    # stream=False — planning is an internal call; no tokens shown to user.
    # Falls back to plain infer() on any error.
    output = ""
    try:
        from core.recursive import recursive_infer
        from utils.config import RECURSIVE_CONFIG
        if (RECURSIVE_CONFIG.get("enabled", True)
                and RECURSIVE_CONFIG.get("recursive_for_plans", True)):
            output = recursive_infer(
                messages,
                task_type="plan",
                user_message=user_message,
                max_depth=2,
                stream=False,
            )
    except Exception:
        pass  # fall through to plain infer below

    if not output:
        from core.inference_v2 import infer
        output = infer(messages, stream=False)

    task_list = parse_task_list(output)
    if not task_list:
        # Fallback: treat whole message as one task
        task_list = [user_message]
    queue = TaskQueue(name=user_message[:60], project_dir=str(Path.cwd()))
    queue.original_request = user_message
    for desc in task_list:
        queue.add(desc)
    queue.save()
    return queue

_SKIP_DIRS = frozenset({'__pycache__', '.git', 'node_modules', '.venv', 'venv', '.mypy_cache'})
_COLLECT_SUFFIXES = frozenset(('.py', '.js', '.ts', '.html', '.css', '.json', '.md'))

def _collect_project_files(max_chars=6000):
    """Read small project files to inject as context between subtasks.
    Recurses one level into subdirectories (e.g. src/, lib/) while skipping
    common noise directories.
    """
    parts = []
    total = 0
    cwd = Path.cwd()

    def _add(f):
        nonlocal total
        if f.name.startswith('.') or f.suffix not in _COLLECT_SUFFIXES:
            return
        try:
            content = f.read_text(encoding='utf-8', errors='replace')
            if len(content) > 3000:
                content = content[:3000] + '\n...[truncated]'
            if total + len(content) > max_chars:
                return
            rel = f.relative_to(cwd)
            parts.append(f"=== {rel} ===\n{content}")
            total += len(content)
        except Exception:
            pass

    for entry in sorted(cwd.iterdir()):
        if total >= max_chars:
            break
        if entry.is_file():
            _add(entry)
        elif entry.is_dir() and entry.name not in _SKIP_DIRS and not entry.name.startswith('.'):
            for f in sorted(entry.iterdir()):
                if total >= max_chars:
                    break
                if f.is_file():
                    _add(f)

    return '\n\n'.join(parts)


# Patterns that indicate a task result is actually a failure
_FAILURE_SIGNALS = [
    "[error]", "[incomplete]", "traceback", "syntaxerror",
    "nameerror", "typeerror", "importerror", "failed",
    "assert", "exception", "1 failed", "errors=",
]


def _is_result_failure(summary):
    """Check if a task result contains failure signals despite claiming success."""
    low = summary.lower()
    return any(sig in low for sig in _FAILURE_SIGNALS)


def _completion_audit(queue):
    """
    After all subtasks finish, check whether the overall goal was met.
    Reports any deliverables from the original request that appear to be missing.
    """
    original = getattr(queue, 'original_request', '')
    if not original:
        return

    # Extract filenames the user expected to exist
    expected_files = _FILE_RE.findall(original)
    missing = [f for f in expected_files if not (Path.cwd() / f).exists()]
    failed_tasks = [t for t in queue.tasks if t.status == 'failed']

    if missing:
        warning(f"[Audit] Requested file(s) not found after all steps: {', '.join(missing)}")
    if failed_tasks:
        warning(f"[Audit] {len(failed_tasks)} task(s) failed: " +
                ', '.join(t.description[:50] for t in failed_tasks))
    if not missing and not failed_tasks:
        info("[Audit] All expected deliverables present.")


def run_queue(queue, yolo=False):
    """
    Execute all pending tasks in queue.
    Each task runs an agent with file context from prior steps.
    Results chain as context to the next task.
    """
    from core.agent import run_agent
    from core.display import update_task_display
    import signal

    prior_results = []
    interrupted = False

    def handle_interrupt(sig, frame):
        nonlocal interrupted
        interrupted = True
        for t in queue.tasks:
            if t.status == 'running':
                t.status = 'pending'
        queue.save()
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGINT, handle_interrupt)

    try:
        for task in queue.tasks:
            if task.status == 'done':
                continue
            if task.status == 'failed':
                continue

            queue.mark_running(task.id)

            # Build context from prior results
            context_prefix = ''
            if prior_results:
                context_prefix = ('Previous steps completed:\n' +
                    '\n'.join(f'- {r}' for r in prior_results[-3:]) +
                    '\n\n')

            # Inject file contents from prior steps so this subtask
            # knows what was actually written (not just a summary).
            file_context = ''
            if prior_results:
                files = _collect_project_files()
                if files:
                    file_context = f"Files created so far:\n\n{files}\n\n"

            # Inject domain-specific guidance based on task content
            guidance = ''
            combined = (getattr(queue, 'original_request', '') + ' ' + task.description).lower()
            if any(k in combined for k in ['http', 'rest', 'api', 'server', 'endpoint']):
                guidance += '\n' + GUIDANCE_HTTP_SERVER + '\n'
            if any(k in combined for k in ['test', 'unittest', 'pytest', 'assert']):
                guidance += '\n' + GUIDANCE_HTTP_TESTING + '\n'
            if any(k in combined for k in ['sqlite', 'database', '.db', 'accounts']):
                guidance += '\n' + GUIDANCE_SQLITE + '\n'
            if any(k in combined for k in ['expense', 'tracker', 'track', 'log', 'record', 'budget', 'note', 'history', 'persist', 'save data', 'store data']):
                guidance += '\n' + GUIDANCE_PERSISTENCE + '\n'

            # Always inject the full original request
            original = getattr(queue, 'original_request', '')
            if original and original.strip() not in task.description:
                prompt = (
                    f"Overall goal: {original}\n\n"
                    f"{context_prefix}{file_context}"
                    f"{guidance}"
                    f"Current step: {task.description}"
                )
            else:
                prompt = context_prefix + file_context + guidance + task.description

            # ── Phase 4: Per-subtask RAG retrieval ───────────────────────────
            # Each subtask gets targeted KB context specific to what it needs
            # (e.g. step 1 gets Flask API docs, step 2 gets unittest patterns).
            # Only for standard/deep breadth — minimal tasks get no extra context.
            # Capped at 1200 chars to leave room for file context + tool hints.
            try:
                from core.recursive import classify_breadth_need
                from core.retrieval import retrieve
                from utils.config import RETRIEVAL_CONFIG, RECURSIVE_CONFIG
                if (RETRIEVAL_CONFIG.get("enabled", True)
                        and RECURSIVE_CONFIG.get("enabled", True)):
                    _task_breadth = classify_breadth_need(task.description)
                    if _task_breadth in ("standard", "deep"):
                        _task_retrieved = retrieve(task.description, budget_chars=1200)
                        if _task_retrieved:
                            prompt += "\n\n" + _task_retrieved
            except Exception:
                pass  # Retrieval unavailable — continue without

            # Remind model to use tools (7B models often forget)
            _target_files = _FILE_RE.findall(task.description)
            if _target_files:
                _fname = _target_files[0]
                prompt += (
                    f'\n\nUse write_file to create {_fname} with the COMPLETE code. '
                    f'Output ONLY: <tool>\n{{"name": "write_file", "args": {{"path": "{_fname}", "content": "...ALL CODE HERE..."}}}}\n</tool>'
                )
            elif any(k in task.description.lower() for k in ['run', 'execute', 'test', 'python']):
                _cmd_match = re.search(r'(?:run|execute|python)\s+(.+)', task.description, re.IGNORECASE)
                _cmd_hint = _cmd_match.group(1).strip() if _cmd_match else "python -m unittest"
                prompt += (
                    f'\n\nUse shell tool. Output ONLY: <tool>\n{{"name": "shell", "args": {{"command": "{_cmd_hint}"}}}}\n</tool>'
                )

            history = []  # isolated message history per subtask

            try:
                result, _ = run_agent(prompt, history, yolo=yolo, _in_subtask=True)

                # Strip common redundant prefixes
                summary = result
                for prefix in ["Done. Final Answer: ", "Final Answer: ",
                               "Done. Final answer: ", "Final answer: "]:
                    if summary.startswith(prefix):
                        summary = summary[len(prefix):]
                        break

                # Validate result — catch false success claims
                _expected_files = _FILE_RE.findall(task.description)
                _missing_files = [
                    f for f in _expected_files
                    if not (Path.cwd() / f).exists()
                ]

                if summary.startswith("[INCOMPLETE]"):
                    queue.mark_failed(task.id, summary)
                    prior_results.append(
                        f'Task {task.id}: {task.description[:60]} -> INCOMPLETE'
                    )
                elif _is_result_failure(summary):
                    queue.mark_failed(task.id, summary)
                    prior_results.append(
                        f'Task {task.id}: {task.description[:60]} -> FAILED: {summary[:80]}'
                    )
                elif _missing_files:
                    _fail_msg = f"Expected file(s) not created: {', '.join(_missing_files)}"
                    warning(_fail_msg)
                    queue.mark_failed(task.id, _fail_msg)
                    prior_results.append(
                        f'Task {task.id}: {task.description[:60]} -> FAILED: {_fail_msg}'
                    )
                else:
                    queue.mark_done(task.id, summary)
                    prior_results.append(
                        f'Task {task.id}: {task.description[:60]} -> {summary[:80]}'
                    )
            except KeyboardInterrupt:
                raise
            except Exception as e:
                queue.mark_failed(task.id, str(e))
                warning(f'Task {task.id} failed: {e}')

            update_task_display(queue)

    except KeyboardInterrupt:
        queue.save()
        from core.display import console
        console.print('\n  [yellow]Task queue paused. Resume with:[/yellow]')
        if queue._path:
            console.print(f'  [cyan]codey --session {queue._path.stem}[/cyan]')
        console.print()
    finally:
        signal.signal(signal.SIGINT, old_handler)

    _completion_audit(queue)
    return queue
