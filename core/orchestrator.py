"""
Orchestrator — plans complex tasks into subtask queues and executes them.
"""
import re
from pathlib import Path
from core.taskqueue import TaskQueue, STATUS_PENDING, STATUS_RUNNING
from utils.logger import info, warning

from prompts.system_prompt import GUIDANCE_HTTP_SERVER, GUIDANCE_HTTP_TESTING, GUIDANCE_SQLITE

PLAN_PROMPT = """Break the task into 2-3 numbered steps. Max 3 steps.
Each step WRITES ONE FILE with its COMPLETE content. No verification or setup steps.

EXAMPLE — "Create REST API with tests":
1. Write app.py: Complete HTTP REST API using http.server.BaseHTTPRequestHandler with all endpoints (/account POST, /deposit POST, /withdraw POST, /balance GET), sqlite3 storage with sqlite3.connect(), atomic transactions, serve on port 8765
2. Write test_api.py: Start server in a thread, test all endpoints using urllib.request HTTP calls (NOT function imports), assert correct responses and balances, shut down server
3. Run tests: python -m unittest test_api

BAD plans (DO NOT generate these):
- "Create app.py" then "Add endpoints to app.py" — NEVER split one file across steps
- "Implement sqlite3 storage" as a separate step — put it IN the app.py step
- "Verify the server works" / "Check output" — NEVER include verification steps
- "Create accounts.db" — NEVER create .db files manually (sqlite3.connect() does it)

RULES:
- ONE step per file. All file content described in that step.
- Test files MUST use HTTP requests (urllib.request), NOT import app functions directly.
- NEVER use port 8080 — reserved for llama-server. Use 8765 or 9000.
- NEVER include git init, .gitignore, or project-setup steps.
- NEVER overwrite .gitignore, README.md, requirements.txt unless explicitly asked.
- Last step can be a shell command to run tests.
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
    _action_kws = [
        "create", "write", "make", "build", "edit", "fix", "run", "execute",
        "install", "add", "delete", "remove", "update", "patch", "refactor",
        "implement", "generate", "rewrite",
        "review", "analyze", "analyse", "audit", "examine", "inspect", "assess",
        "read", "look at", "show me", "check",
    ]
    _has_action = any(k in msg for k in _action_kws)
    
    # Question starters that indicate Q&A (not a task)
    _question_starters = (
        "what", "why", "how", "when", "where", "who", "which",
        "is ", "are ", "do ", "does ", "can ", "could ", "would ",
        "should ", "will ", "was ", "were ", "has ", "have ",
    )
    _qa_phrases = ["tell me", "explain", "help me understand", "what can you"]
    
    # If no action keyword AND looks like a question, NOT complex
    if not _has_action and (
        msg.endswith("?") or
        msg.startswith(_question_starters) or
        any(k in msg for k in _qa_phrases)
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
        return signals >= 3
    else:
        return signals >= 4

def parse_task_list(model_output):
    """Extract numbered steps from model output."""
    tasks = []
    for line in model_output.splitlines():
        line = line.strip()
        m = re.match(r'^(\d+)[.)\s]+(.+)$', line)
        if m and len(m.group(2)) > 5:
            tasks.append(m.group(2).strip())
    return _postprocess_plan(tasks[:5])


# Steps that produce no useful output — pure verification/review
_WASTE_PATTERNS = [
    "verify", "check the", "check output", "review the code",
    "test the server", "navigate to", "save file", "open browser",
    "confirm that", "ensure that", "make sure",
]

# Filename extraction pattern
_FILE_RE = re.compile(r'\b(\w+\.(?:py|js|ts|html|css|json|yaml|yml|toml|txt|md|sh))\b')


def _postprocess_plan(tasks):
    """
    Post-process plan steps from the model to fix common issues:
    1. Merge steps that target the same file
    2. Remove waste steps (verify, check, review)
    3. Remove .db/.sqlite creation steps
    4. Cap at 3 steps
    """
    if not tasks:
        return tasks

    # Remove waste steps
    filtered = []
    for t in tasks:
        t_low = t.lower()
        # Skip pure verification steps
        if any(p in t_low for p in _WASTE_PATTERNS) and not any(
            k in t_low for k in ["write", "create", "implement", "build"]
        ):
            continue
        # Skip .db/.sqlite creation steps
        if any(ext in t_low for ext in ['.db', '.sqlite', '.sqlite3']) and \
           any(k in t_low for k in ['create', 'set up', 'initialize']):
            if not any(k in t_low for k in ['write', 'python', '.py']):
                continue
        filtered.append(t)

    if not filtered:
        return tasks[:1]  # Don't return empty — keep at least one

    # Merge steps targeting the same file
    merged = []
    seen_files = {}  # filename -> index in merged list
    for t in filtered:
        files_in_step = _FILE_RE.findall(t)
        merged_into = None
        for f in files_in_step:
            if f in seen_files:
                merged_into = seen_files[f]
                break
        if merged_into is not None:
            # Append this step's description to the existing step
            merged[merged_into] = merged[merged_into] + "; also: " + t
        else:
            idx = len(merged)
            merged.append(t)
            for f in files_in_step:
                seen_files[f] = idx

    return merged[:3]

def plan_tasks(user_message, project_context=''):
    """Ask model to plan the task. Returns TaskQueue."""
    from core.inference_v2 import infer
    plan_prompt = PLAN_PROMPT
    if project_context:
        plan_prompt += f'\nProject context:\n{project_context}'
    # Inject git-repo awareness so model never adds "git init / create .gitignore" steps
    try:
        from core.githelper import is_git_repo
        if is_git_repo():
            plan_prompt += (
                '\nIMPORTANT: Already inside an existing git repository. '
                'Do NOT add git init, .gitignore creation, or initial commit steps.'
            )
    except Exception:
        pass
    # Inject prompt directly into user message — more reliable than system role
    messages = [
        {'role': 'user', 'content': plan_prompt + '\n\nTask: ' + user_message + '\n\nNumbered steps:'}
    ]
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

def _collect_project_files(max_chars=6000):
    """Read small project files to inject as context between subtasks."""
    parts = []
    total = 0
    for f in sorted(Path.cwd().iterdir()):
        if f.is_file() and f.suffix in ('.py', '.js', '.ts', '.html', '.css', '.json'):
            if f.name.startswith('.'):
                continue
            try:
                content = f.read_text(encoding='utf-8', errors='replace')
                if len(content) > 3000:
                    content = content[:3000] + '\n...[truncated]'
                if total + len(content) > max_chars:
                    break
                parts.append(f"=== {f.name} ===\n{content}")
                total += len(content)
            except Exception:
                pass
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

    return queue
