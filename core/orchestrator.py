"""
Orchestrator — plans complex tasks into subtask queues and executes them.
"""
import re
from pathlib import Path
from core.taskqueue import TaskQueue, STATUS_PENDING, STATUS_RUNNING
from utils.logger import info, warning

PLAN_PROMPT = """Break the task into 2-5 numbered steps. Max 5 steps.
Each step must be a single concrete action: create a file, edit a file, or run a command.
NEVER include steps like "open in editor", "save file", "navigate to directory", "review code", or "think about structure".
NEVER include git init, .gitignore creation, initial commit, or project-setup steps when already in an existing git repository.
NEVER overwrite existing project files like .gitignore, README.md, or requirements.txt unless the task explicitly asks for it.
Output ONLY the numbered list of actions."""

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
    return tasks[:5]

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

def run_queue(queue, yolo=False):
    """
    Execute all pending tasks in queue.
    Each task runs an isolated agent with shared file memory.
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
        # Mark current running task as pending so it restarts on resume
        for t in queue.tasks:
            if t.status == 'running':
                t.status = 'pending'
        queue.save()
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGINT, handle_interrupt)

    try:
        for task in queue.tasks:
            if task.status == 'done':
                continue  # already completed, skip on resume
            if task.status == 'failed':
                continue  # skip previously failed tasks

            queue.mark_running(task.id)

            # Build context from prior results
            context_prefix = ''
            if prior_results:
                context_prefix = ('Previous steps completed:\n' +
                    '\n'.join(f'- {r}' for r in prior_results[-3:]) +
                    '\n\nNow: ')

            prompt = context_prefix + task.description
            history = []  # isolated context per subtask

            try:
                result, _ = run_agent(prompt, history, yolo=yolo, _in_subtask=True)
                
                # Strip common redundant prefixes from task result summary
                summary = result
                for prefix in ["Done. Final Answer: ", "Final Answer: ", "Done. Final answer: ", "Final answer: "]:
                    if summary.startswith(prefix):
                        summary = summary[len(prefix):]
                        break
                
                queue.mark_done(task.id, summary)
                prior_results.append(f'Task {task.id}: {task.description[:60]} -> {summary[:80]}')
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
