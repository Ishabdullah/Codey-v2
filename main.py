#!/usr/bin/env python3
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import console, info, success, error, warning, separator
from utils.config import CODEY_VERSION
from core.loader_v2 import get_loader
from core.inference_v2 import infer, was_last_streamed
from core.agent import run_agent
from core import context as ctx
from core.sysmon import get_monitor

BANNER = f"""[bold green]
  ██████╗ ██████╗ ██████╗ ███████╗██╗   ██╗
 ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗ ██╔╝
 ██║     ██║   ██║██║  ██║█████╗   ╚████╔╝
 ██║     ██║   ██║██║  ██║██╔══╝    ╚██╔╝
 ╚██████╗╚██████╔╝██████╔╝███████╗   ██║
  ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝   ╚═╝
[/bold green][dim]  v{CODEY_VERSION} · Local AI Coding Assistant · Termux[/dim]
"""

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Codey-v2 - Local AI coding assistant")
    parser.add_argument("prompt",       nargs="?")
    parser.add_argument("--yolo",       action="store_true", help="Skip confirmations")
    parser.add_argument("--threads",    type=int)
    parser.add_argument("--ctx",        type=int)
    parser.add_argument("--version",    action="store_true")
    parser.add_argument("--chat",       action="store_true")
    parser.add_argument("--read",       nargs="+", metavar="FILE")
    parser.add_argument("--init",       action="store_true", help="Generate CODEY.md")
    parser.add_argument("--fix",        metavar="FILE", help="Run file, auto-fix errors")
    parser.add_argument("--tdd",        metavar="FILE", help="TDD mode: source.py test_source.py")
    parser.add_argument("--tests",      metavar="FILE", help="Test file for --tdd mode")
    parser.add_argument("--session",    nargs="?", const="list", metavar="ID", help="Resume saved session")
    parser.add_argument("--clear-session", action="store_true", help="Clear saved session")
    parser.add_argument("--plan", action="store_true", help="Enable plan mode for complex tasks")
    parser.add_argument("--no-plan", action="store_true", help="Disable orchestration/planning for complex tasks")
    parser.add_argument("--daemon",     action="store_true", help="Run in daemon mode (v2 feature)")
    parser.add_argument("--no-resume",  action="store_true", help="Start fresh, ignore saved session")
    parser.add_argument("--allow-self-mod", action="store_true", help="Allow self-modification with checkpoint enforcement")
    # Fine-tuning commands (v2.3.0)
    parser.add_argument("--finetune",   action="store_true", help="Export fine-tuning dataset and generate Colab notebook")
    parser.add_argument("--ft-days",    type=int, default=30, help="Days of history to include (default: 30)")
    parser.add_argument("--ft-quality", type=float, default=0.7, help="Min quality threshold 0.0-1.0 (default: 0.7)")
    parser.add_argument("--ft-model",   choices=["7b"], default="7b", help="Model variant for fine-tuning")
    parser.add_argument("--ft-output",  type=str, help="Output directory (default: ~/Downloads/codey-finetune)")
    parser.add_argument("--import-lora", metavar="PATH", help="Import LoRA adapter from path")
    parser.add_argument("--lora-model", choices=["primary"], default="primary", help="Model for LoRA import")
    parser.add_argument("--lora-quant", type=str, default="q4_0", help="Quantization for merged model")
    parser.add_argument("--lora-merge", action="store_true", help="Merge LoRA on-device (requires llama.cpp)")
    return parser.parse_args()

def apply_overrides(args):
    import os
    from utils import config
    from utils.logger import info
    
    if args.yolo:
        config.AGENT_CONFIG["confirm_shell"] = False
        config.AGENT_CONFIG["confirm_write"] = False
        info("YOLO mode: confirmations disabled.")
    
    # Check for self-modification enablement (CLI flag or env var)
    allow_self_mod = args.allow_self_mod or os.environ.get("ALLOW_SELF_MOD", "0") == "1"
    if allow_self_mod:
        config.AGENT_CONFIG["allow_self_modification"] = True
        info("Self-modification enabled: Codey can modify its own source files (with checkpoints).")
    
    if args.threads:
        config.MODEL_CONFIG["n_threads"] = args.threads
    if args.ctx:
        config.MODEL_CONFIG["n_ctx"] = args.ctx

def _daemon_is_running() -> bool:
    """Check if the daemon is running (PID file check)."""
    try:
        from core.daemon import check_pid_file
        return check_pid_file()
    except Exception:
        return False


def shutdown():
    # Stop system monitor
    try:
        get_monitor().stop()
    except Exception:
        pass
    # If daemon is running, leave llama-server alive for it
    if _daemon_is_running():
        return
    # Unload model and kill llama-server on port 8080
    try:
        from core.loader_v2 import get_loader
        get_loader().unload()
    except Exception:
        pass
    # SIGKILL any remaining llama-server
    try:
        import subprocess
        subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True, timeout=5)
    except Exception:
        pass

def run_init():
    from core.project import detect_project
    from core.codeymd import get_init_prompt, write_codeymd, find_codeymd
    from core.inference_v2 import infer
    existing = find_codeymd()
    if existing:
        warning(f"CODEY.md already exists at {existing}")
        ans = console.input("Overwrite? [y/N]: ").strip().lower()
        if ans not in ("y", "yes"):
            info("Aborted.")
            return
    proj = detect_project()
    info(f"Analyzing {proj['type']} project in {proj['cwd']}...")
    messages = [
        {"role": "system", "content": "You are a technical writer. Output only clean markdown, no preamble."},
        {"role": "user",   "content": get_init_prompt(proj)}
    ]
    info("Generating CODEY.md...")
    content = infer(messages, stream=False)
    if content.startswith("[ERROR]"):
        error(f"Generation failed: {content}")
        return
    path = write_codeymd(content)
    success(f"CODEY.md written to {path}") if not path.startswith("[ERROR]") else error(path)

def _try_daemon_plan(prompt: str, no_plan: bool = False):
    """
    If the daemon is running, send the prompt through its Unix socket so that
    _handle_command is called and plannd (DeepSeek 1.5B) gets a chance to produce
    a numbered plan.

    Returns the list of step strings on success, or None so the caller falls back
    to direct run_agent() — identical to pre-plannd behaviour.

    Failure modes handled silently:
      - Daemon not running         → None
      - plannd not yet loaded      → None (no "plan" key in response)
      - Socket timeout (60 s)      → None
      - Any exception              → None
    """
    if no_plan:
        return None
    try:
        from core.daemon import is_daemon_running, send_command
        if not is_daemon_running():
            return None
        response = send_command("command", {"prompt": prompt, "no_plan": False, "plan_only": True})
        plan = response.get("plan")
        if plan and isinstance(plan, list) and len(plan) > 1:
            return plan
    except Exception:
        pass  # daemon unavailable, plannd not ready, or timed out → fall through
    return None


def _extract_filename_from_step(step: str) -> str:
    """
    Extract a filename from a plan step description.

    Matches backtick-quoted names first (e.g. `wordcount.py`), then falls back
    to any word containing a dot-extension (e.g. fibonacci.py).
    Returns an empty string if no filename is found.
    """
    import re
    m = re.search(r'`([^`]+\.[a-zA-Z0-9]{1,10})`', step)
    if m:
        return m.group(1)
    m = re.search(r'\b(\w[\w.-]*\.[a-zA-Z0-9]{1,5})\b', step)
    if m:
        return m.group(1)
    return ""


def _run_with_plan(prompt: str, history: list, yolo: bool, use_plan: bool, no_plan: bool):
    """
    Execute a user prompt, routing through the daemon for planning when available.

    If the daemon is running and plannd returns a plan:
      1. Print the numbered plan from DeepSeek before any execution begins.
      2. Run each step through run_agent() locally (7B model, visible in terminal).
      3. After file-creation steps, verify the file was actually written.
         If not, retry the step once before continuing.

    Otherwise fall back to a direct run_agent() call — identical to existing behaviour.

    Returns (response, updated_history) with the same contract as run_agent().
    """
    import re
    from pathlib import Path
    import os

    plan = _try_daemon_plan(prompt, no_plan)

    if plan:
        separator()
        console.print("[bold cyan]Plan from DeepSeek:[/bold cyan]")
        for i, step in enumerate(plan, 1):
            console.print(f"  [bold cyan]{i}.[/bold cyan] {step}")
        separator()

        _CREATE_KEYWORDS = {"create", "write", "make", "build", "generate", "save"}

        # Retrieve once on the full user prompt so every step gets the richest
        # possible KB context instead of querying on terse planner-generated text.
        _plan_rag = ""
        try:
            from core.retrieval import retrieve
            _plan_rag = retrieve(prompt) or ""
        except Exception:
            pass

        response = ""
        for i, step in enumerate(plan, 1):
            console.print(f"\n[dim]── Step {i}/{len(plan)}: {step}[/dim]")
            step_resp, history = run_agent(step, history, yolo=yolo, no_plan=True,
                                           _plan_rag_block=_plan_rag)
            response = step_resp or response

            # Post-step: if this step was supposed to create a file, verify it
            # actually exists. If not, retry once before moving to the next step.
            step_low = step.lower()
            if any(k in step_low for k in _CREATE_KEYWORDS):
                fname = _extract_filename_from_step(step)
                if fname:
                    target = Path(os.getcwd()) / fname
                    if not target.exists():
                        warning(f"Step {i}: '{fname}' not found after step — retrying")
                        console.print(f"\n[dim]↺  Step {i}/{len(plan)} retry (file not created)[/dim]")
                        step_resp, history = run_agent(step, history, yolo=yolo, no_plan=True,
                                                       _plan_rag_block=_plan_rag)
                        response = step_resp or response

        return response, history

    # No plan available — run directly as before
    return run_agent(prompt, history, yolo=yolo, use_plan=use_plan, no_plan=no_plan)


def print_diff(diff_output: str):
    for line in diff_output.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"[green]{line}[/green]")
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            console.print(f"[cyan]{line}[/cyan]")
        else:
            console.print(line)

def handle_command(user_input: str, history: list, yolo: bool = False) -> tuple[bool, list]:
    cmd = user_input.strip()
    low = cmd.lower()

    if low in ("/exit", "/quit", "exit", "quit"):
        from core.sessions import save_session
        save_session(history)
        console.print("[dim]Session saved. Goodbye![/dim]")
        shutdown()
        sys.exit(0)

    if low == "/clear":
        history.clear()
        ctx.clear_context()
        from core.filehistory import clear_history
        clear_history()
        from core.sessions import clear_session
        clear_session()
        success("History, context, undo history, and saved session cleared.")
        return True, history

    if low == "/summarize":
        if len(history) < 4:
            info("Not enough history to summarize (need at least 2 turns).")
        else:
            from core.summarizer import summarize_history
            from core.tokens import estimate_messages_tokens
            old_tokens = estimate_messages_tokens(history)
            history = summarize_history(history)
            new_tokens = estimate_messages_tokens(history)
            success(f"Context compressed: {old_tokens} → {new_tokens} tokens")
        return True, history

    if low.startswith("/undo"):
        from core.filehistory import undo, list_history
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            hist = list_history()
            if not hist:
                info("Nothing to undo this session.")
            else:
                console.print("[bold]Files with undo history:[/bold]")
                for path, timestamps in hist.items():
                    console.print(f"  📄 {Path(path).name} — {', '.join(timestamps)}")
                info("Usage: /undo <filename>")
        else:
            result = undo(parts[1])
            error(result) if result.startswith("[ERROR]") else None
        return True, history

    if low.startswith("/diff"):
        from core.filehistory import diff, list_history
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            hist = list_history()
            if not hist:
                info("No file changes this session.")
            else:
                console.print("[bold]Changed files:[/bold]")
                for path in hist:
                    console.print(f"  📄 {Path(path).name}")
                info("Usage: /diff <filename>")
        else:
            result = diff(parts[1])
            if result.startswith("[ERROR]") or result.startswith("No"):
                info(result)
            else:
                print_diff(result)
        return True, history

    if low.startswith("/search"):
        from core.search import search_in_project, search_definitions
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            info("Usage: /search <pattern> [path]")
            info("       /search def run_agent")
            info("       /search import core/")
        else:
            query_parts = parts[1].rsplit(maxsplit=1)
            # Only treat last arg as path if it looks like a path (starts with . / ~ or is a dir)
            if len(query_parts) > 1 and (
                query_parts[-1].startswith((".", "/", "~")) or
                os.path.isdir(query_parts[-1])
            ):
                pattern = query_parts[0]
                search_path = query_parts[1]
            else:
                pattern = parts[1]  # whole thing is the pattern
                search_path = "."
            result = search_in_project(pattern, search_path)
            console.print(result)
        return True, history

    if low.startswith("/git"):
        from core.githelper import (
            git_commit, git_push, git_status, git_log, is_git_repo,
            git_branches, git_branch_create, git_checkout, git_merge,
            detect_conflicts, get_conflict_sections,
            git_diff_for_commit, git_commit_log_messages, generate_commit_message,
            git_current_branch,
        )
        parts = cmd.split(maxsplit=2)

        if not is_git_repo():
            error("Not a git repository.")
            return True, history

        sub = parts[1].strip() if len(parts) > 1 else ""
        sub_low = sub.lower()
        arg = parts[2].strip() if len(parts) > 2 else ""

        if sub_low == "status" or sub == "":
            console.print(git_status())

        elif sub_low == "log":
            console.print(git_log())

        elif sub_low == "branches":
            console.print(git_branches())

        elif sub_low == "branch":
            if not arg:
                error("Usage: /git branch <name>")
            else:
                result = git_branch_create(arg)
                success(result) if not result.startswith("[ERROR]") else error(result)

        elif sub_low == "checkout":
            if not arg:
                error("Usage: /git checkout <branch>")
            else:
                current = git_current_branch()
                console.print(f"Switching from [bold]{current}[/bold] → [bold]{arg}[/bold]")
                try:
                    confirm = input("Confirm? [y/N] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    confirm = "n"
                if confirm == "y":
                    result = git_checkout(arg)
                    success(result) if not result.startswith("[ERROR]") else error(result)
                else:
                    info("Checkout cancelled.")

        elif sub_low == "merge":
            if not arg:
                error("Usage: /git merge <branch>")
            else:
                result = git_merge(arg)
                if result.startswith("OK:"):
                    success(result[3:].strip() or "Merged successfully.")
                elif result.startswith("[CONFLICT]"):
                    warning(result)
                    # Conflict resolution flow
                    conflict_files = detect_conflicts()
                    if conflict_files:
                        console.print(f"\n[bold red]Conflicts in {len(conflict_files)} file(s):[/bold red]")
                        for cf in conflict_files:
                            console.print(f"  • {cf}")
                        try:
                            resolve = input("\nAsk Codey to resolve conflicts? [y/N] ").strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            resolve = "n"
                        if resolve == "y":
                            conflict_context = []
                            for cf in conflict_files[:3]:  # cap at 3 files
                                sections = get_conflict_sections(cf)
                                if sections.get("has_conflicts"):
                                    conflict_context.append(
                                        f"File: {cf}\n"
                                        f"OURS (HEAD):\n{sections['ours']}\n"
                                        f"THEIRS ({arg}):\n{sections['theirs']}\n"
                                        f"({sections['count']} conflict block(s))"
                                    )
                            prompt = (
                                f"There are merge conflicts after merging branch '{arg}'. "
                                f"Please resolve them.\n\n" + "\n\n".join(conflict_context)
                            )
                            _, history = run_agent(prompt, history, yolo=yolo)
                    else:
                        info("Resolve conflicts manually, then run: /git commit")
                else:
                    error(result)

        elif sub_low == "diff":
            diff = git_diff_for_commit()
            console.print(diff or "(no diff)")

        elif sub_low == "commit":
            # Smart AI-generated commit message
            if arg:
                # Message provided directly: /git commit <message>
                result = git_commit(arg)
            else:
                # Generate message from diff
                diff = git_diff_for_commit()
                if diff == "(no diff available)":
                    info("Nothing to commit — working tree clean.")
                    return True, history
                console.print("[dim]Analyzing diff to generate commit message…[/dim]")
                history_msgs = git_commit_log_messages()
                suggested = generate_commit_message(diff, history_msgs)
                console.print(f"\nSuggested message: [bold cyan]{suggested}[/bold cyan]")
                try:
                    user_msg = input("Press Enter to accept, or type a new message: ").strip()
                except (EOFError, KeyboardInterrupt):
                    info("Commit cancelled.")
                    return True, history
                final_msg = user_msg if user_msg else suggested
                result = git_commit(final_msg)
            if result.startswith("[ERROR]"):
                error(result)
            elif result.startswith("Nothing"):
                info(result)
            else:
                success(result)

        elif sub_low.startswith("push"):
            result = git_push()
            success(result) if not result.startswith("[ERROR]") else error(result)

        elif sub_low == "conflicts":
            conflict_files = detect_conflicts()
            if not conflict_files:
                success("No conflicts detected.")
            else:
                console.print(f"[bold red]Conflicted files ({len(conflict_files)}):[/bold red]")
                for cf in conflict_files:
                    sections = get_conflict_sections(cf)
                    blocks = sections.get("count", "?")
                    console.print(f"  • {cf}  ({blocks} block(s))")

        else:
            # Backward compat: treat sub+arg as a raw commit message
            raw_msg = (sub + (" " + arg if arg else "")).strip()
            result = git_commit(raw_msg)
            if result.startswith("[ERROR]"):
                error(result)
            elif result.startswith("Nothing"):
                info(result)
            else:
                success(result)

        return True, history

    if low.startswith("/sessions"):
        from core.sessions import list_sessions
        sessions = list_sessions()
        if not sessions:
            info("No saved sessions.")
        else:
            console.print("[bold]Saved sessions:[/bold]")
            for s in sessions:
                console.print(f"  📁 {Path(s['project']).name} — {s['turns']} turns — {s['saved_at']}")
        return True, history

    if low.startswith("/load"):
        parts = cmd.split()[1:]
        if not parts:
            info("Usage: /load <file|glob|dir> ...")
        else:
            for target in parts:
                p = Path(target)
                if p.is_dir():
                    ctx.load_directory(str(p))
                elif "*" in target or "?" in target:
                    ctx.load_glob(target)
                else:
                    ctx.load_file(target)
        return True, history

    if low.startswith("/read"):
        parts = cmd.split()[1:]
        if not parts:
            info("Usage: /read <file1> [file2] ...")
        else:
            for f in parts:
                ctx.load_file(f)
        return True, history

    if low.startswith("/unread"):
        parts = cmd.split()[1:]
        for f in parts:
            ctx.unload_file(f)
        return True, history

    if low == "/context":
        from core.memory import memory as _mem
        s = _mem.status()
        loaded = s['file_names']
        if loaded:
            console.print(f"[bold]Files in memory (turn {s['turn']}):[/bold]")
            for fname in loaded:
                files = _mem._files
                for k, r in files.items():
                    if r.name == fname:
                        age = s['turn'] - r.last_used_turn
                        score_hint = f"last used {age} turns ago"
                        console.print(f"  📄 {r.name} ({r.tokens} tokens, {score_hint})")
        else:
            info("No files in memory. Use /load or /read to add files.")
        return True, history

    if low == "/project":
        from core.project import detect_project
        proj = detect_project()
        console.print(f"[bold]Project:[/bold] {proj['type']} · {proj['cwd']}")
        if proj["key_files"]:
            console.print(f"[bold]Key files:[/bold] {', '.join(proj['key_files'])}")
        return True, history

    if low == "/init":
        run_init()
        return True, history

    if low == "/memory":
        from core.codeymd import find_codeymd, read_codeymd
        path = find_codeymd()
        if path:
            console.print(f"[bold]CODEY.md[/bold] ({path}):\n")
            console.print(read_codeymd())
        else:
            info("No CODEY.md found. Run /init to generate one.")
        return True, history

    if low.startswith("/memory-status"):
        from core.memory import memory as _mem
        from core.tokens import estimate_tokens, usage_bar
        s = _mem.status()
        console.print(f"[bold]Memory status — turn {s['turn']}:[/bold]")
        console.print(f"  Files in memory:  {s['files']} — {', '.join(s['file_names']) or 'none'}")
        console.print(f"  Summary:          {s['summary_tokens']} tokens")
        if _mem.get_summary():
            console.print(f"[dim]{_mem.get_summary()}[/dim]")
        return True, history

    if low.startswith("/memory-v2"):
        from core.memory import memory as _mem
        s = _mem.status()
        console.print("[bold]Four-Tier Memory Status:[/bold]")
        console.print()
        # Tier 1: Working Memory
        console.print("[bold cyan]1. Working Memory[/bold cyan]")
        console.print(f"   Files: {s['working']['files']} — {', '.join(s['working']['file_names']) or 'none'}")
        console.print(f"   Tokens: {s['working']['total_tokens']} / {s['working']['turn']} turns")
        console.print()
        # Tier 2: Project Memory
        console.print("[bold cyan]2. Project Memory (never evicted)[/bold cyan]")
        _proj_files = _mem.project.get_protected_files()
        console.print(f"   Protected files: {len(_proj_files)}")
        for pf in _proj_files[:10]:
            console.print(f"     • {pf}")
        if len(_proj_files) > 10:
            console.print(f"     ... and {len(_proj_files) - 10} more")
        console.print()
        # Tier 3: Long-term Memory
        console.print("[bold cyan]3. Long-term Memory (embeddings)[/bold cyan]")
        _lt = s['longterm']
        if _lt['available']:
            console.print(f"   Status: available")
            console.print(f"   Embeddings: {_lt['embeddings']}")
        else:
            console.print(f"   Status: unavailable ({_lt.get('init_error', 'not initialized')})")
        console.print()
        # Tier 4: Episodic Memory
        console.print("[bold cyan]4. Episodic Memory (action log)[/bold cyan]")
        _recent = _mem.episodic.get_recent(10)
        if _recent:
            console.print(f"   Recent actions (last {len(_recent)}):")
            for action in _recent[-5:]:
                _action = action.get('action', 'unknown')
                _details = action.get('details', '')[:60]
                _ts = action.get('timestamp', '')
                console.print(f"     [{_ts}] {_action}: {_details}")
        else:
            console.print("   No recent actions logged")
        console.print()
        return True, history

    if low.startswith("/cwd"):
        parts = cmd.split(maxsplit=1)
        if len(parts) > 1:
            try:
                os.chdir(parts[1])
                new_cwd = os.getcwd()
                # Update WORKSPACE_ROOT so Filesystem boundary checks use new dir
                import utils.config as _cfg
                from pathlib import Path as _Path
                _cfg.WORKSPACE_ROOT = _Path(new_cwd).resolve()
                # Reset Filesystem singleton so next tool call picks up new workspace
                from core.filesystem import reset_filesystem
                reset_filesystem()
                # Invalidate project cache (repo map, project type)
                from core.project import invalidate_cache
                invalidate_cache()
                # Invalidate .codeyignore pattern cache for old cwd
                from core import context as _ctx
                _ctx._ignore_cache.clear()
                success(f"Working directory: {new_cwd}")
            except Exception as e:
                error(str(e))
        else:
            info(f"Current directory: {os.getcwd()}")
        return True, history

    if low.startswith("/ignore"):
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            info("Usage: /ignore <pattern>")
        else:
            pattern = parts[1].strip()
            ignore_file = Path(os.getcwd()) / ".codeyignore"
            try:
                with open(ignore_file, "a") as f:
                    f.write(f"\n{pattern}")
                success(f"Added '{pattern}' to .codeyignore")
            except Exception as e:
                error(f"Could not update .codeyignore: {e}")
        return True, history

    if low == "/learning":
        from core.learning import get_learning_manager
        learning = get_learning_manager()
        status = learning.get_status()
        
        console.print("\n[bold]Learning System Status[/bold]\n")
        
        # Preferences
        console.print("[bold cyan]Preferences:[/bold cyan]")
        prefs = status["preferences"]["preferences"]
        if prefs:
            for key, value in prefs.items():
                conf = status["preferences"]["confidence"].get(key, 0)
                bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
                console.print(f"  {key}: [green]{value}[/green] [{bar}]")
        else:
            console.print("  [dim]No preferences learned yet[/dim]")
        
        # Errors
        console.print("\n[bold cyan]Error Database:[/bold cyan]")
        console.print(f"  Patterns: {status['errors']['total_patterns']}")
        console.print(f"  Occurrences: {status['errors']['total_occurrences']}")
        console.print(f"  Fixed: {status['errors']['total_fixed']}")
        console.print(f"  Success Rate: {status['errors']['success_rate']}")
        
        # Strategies
        console.print("\n[bold cyan]Strategy Tracker:[/bold cyan]")
        console.print(f"  Strategies: {status['strategies']['total_strategies']}")
        console.print(f"  Total Attempts: {status['strategies']['total_attempts']}")
        console.print(f"  Overall Success: {status['strategies']['overall_success_rate']:.1f}%")
        
        top = status['strategies'].get('top_strategies', [])
        if top:
            console.print("  [dim]Top Strategies:[/dim]")
            for s in top[:3]:
                console.print(f"    {s['name']}: {s['success_rate']*100:.0f}% ({s['attempts']} attempts)")
        
        return True, history

    # ── /review ──────────────────────────────────────────────────────────────
    if low.startswith("/review"):
        from core.linter import run_all_linters, get_available_linters
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            info("Usage: /review <file.py>")
            return True, history

        filepath = parts[1].strip()
        from pathlib import Path as _P
        if not _P(filepath).exists():
            error(f"File not found: {filepath}")
            return True, history

        available = get_available_linters()
        if not available:
            warning("No linters installed. Get better results with: pip install ruff")

        console.print(f"\n[bold]Code Review:[/bold] {filepath}\n")
        all_results = run_all_linters(filepath)
        total_issues = 0
        review_lines = []

        for tool_name, issues in all_results:
            if tool_name == "syntax" and not issues:
                continue   # skip clean syntax row — clutters the output
            errors_only = [i for i in issues if i.severity == "error"]
            warnings_only = [i for i in issues if i.severity != "error"]
            if issues:
                console.print(f"  [bold cyan]{tool_name}[/bold cyan] — {len(issues)} issue(s):")
                for issue in (errors_only + warnings_only)[:20]:
                    color = "red" if issue.severity == "error" else "yellow"
                    sym = "✗" if issue.severity == "error" else "⚠"
                    console.print(f"    [{color}]{sym} Line {issue.line}[/{color}] [{issue.code}] {issue.message}")
                    review_lines.append(f"Line {issue.line}: [{issue.code}] {issue.message}")
                if len(issues) > 20:
                    console.print(f"    [dim]... and {len(issues) - 20} more[/dim]")
                total_issues += len(issues)
            else:
                console.print(f"  [bold cyan]{tool_name}[/bold cyan] — [green]clean[/green]")

        if not all_results:
            console.print("  [dim]No linters available. Run: pip install ruff[/dim]")

        console.print(f"\n  [bold]Total:[/bold] {total_issues} issue(s)\n")

        # Offer agent explanation + fix
        if total_issues > 0 and review_lines:
            try:
                ans = console.input("  Ask Codey to explain and fix? [y/N]: ").strip().lower()
                if ans in ("y", "yes"):
                    ctx_block = "\n".join(review_lines[:15])
                    response, history = run_agent(
                        f"Review {filepath} and fix these linter issues (read the file first):\n{ctx_block}",
                        history, yolo=yolo,
                    )
                    if response and not response.startswith("["):
                        separator()
                        console.print(f"\n[bold green]Codey-v2:[/bold green] {response}")
                        separator()
                    from core.sessions import save_session
                    save_session(history)
            except (KeyboardInterrupt, EOFError):
                pass
        return True, history

    # ── /voice ───────────────────────────────────────────────────────────────
    if low.startswith("/voice"):
        from core.voice import get_voice
        v = get_voice()
        parts = cmd.split()
        sub = parts[1].lower() if len(parts) > 1 else ""

        if sub == "on":
            v.turn_on()
        elif sub == "off":
            v.turn_off()
        elif sub == "listen":
            text = v.listen()
            if text:
                info(f"Voice input: {text}")
                # Run as agent task immediately
                try:
                    response, history = run_agent(text, history, yolo=yolo)
                    if response and not response.startswith("["):
                        separator()
                        console.print(f"\n[bold green]Codey-v2:[/bold green] {response}")
                        separator()
                        if v.enabled and v.tts_available():
                            try:
                                v.speak(response)
                            except KeyboardInterrupt:
                                pass
                    from core.sessions import save_session
                    save_session(history)
                except KeyboardInterrupt:
                    console.print("\n[dim]Interrupted.[/dim]")
        elif sub == "rate":
            if len(parts) > 2:
                try:
                    v.set_rate(float(parts[2]))
                except ValueError:
                    error("Usage: /voice rate <number>  (e.g. /voice rate 1.5)")
            else:
                error("Usage: /voice rate <number>  (e.g. /voice rate 1.5)")
        elif sub == "pitch":
            if len(parts) > 2:
                try:
                    v.set_pitch(float(parts[2]))
                except ValueError:
                    error("Usage: /voice pitch <number>  (e.g. /voice pitch 0.9)")
            else:
                error("Usage: /voice pitch <number>")
        elif sub == "speak" and len(parts) > 2:
            # /voice speak <text> — one-shot TTS test
            text_to_speak = " ".join(parts[2:])
            if not v.speak(text_to_speak):
                warning("TTS unavailable. Install Termux:API.")
        else:
            # /voice with no sub-command → show status + help
            console.print(f"\n  {v.status()}\n")
            console.print("  [bold]Voice commands:[/bold]")
            console.print("    /voice on              Enable voice mode (TTS + STT)")
            console.print("    /voice off             Disable voice mode")
            console.print("    /voice listen          One-shot voice input → agent")
            console.print("    /voice rate <n>        Set TTS speed  (default 1.0)")
            console.print("    /voice pitch <n>       Set TTS pitch  (default 1.0)")
            console.print("    /voice speak <text>    Test TTS with given text\n")
        return True, history

    if low.startswith("/peer"):
        from core.peer_cli import get_peer_cli_manager
        mgr = get_peer_cli_manager()
        parts = cmd.split(maxsplit=2)
        available = mgr.available()
        if not available:
            warning("No peer CLIs found (claude / gemini / qwen).")
            return True, history

        # /peer → list available CLIs
        if len(parts) == 1:
            console.print("[bold]Available peer CLIs:[/bold]")
            for c in available:
                console.print(f"  [cyan]{c.name}[/cyan]  —  {c.description}")
            console.print("\nUsage: /peer <name> <task>  or  /peer <name>  (open interactive)")
            console.print("       /peer gemini explain this function")
            console.print("       /peer qwen write a hello world in Python")
            return True, history

        # /peer <name> <task>  OR  /peer <task>  (auto-pick)
        by_name = {c.name: c for c in available}
        if len(parts) >= 3 and parts[1].lower() in by_name:
            cli = by_name[parts[1].lower()]
            task = parts[2]
        elif len(parts) >= 2 and parts[1].lower() in by_name:
            cli = by_name[parts[1].lower()]
            task = ""
        else:
            # No CLI name given — auto-pick based on task
            task = " ".join(parts[1:])
            task_type = mgr.detect_task_type(task, [])
            cli = mgr.select_cli(task_type)
            if not cli:
                error("No peer CLIs available.")
                return True, history
            info(f"Auto-selected: {cli.description}")

        # Pass the raw task — no wrapping needed for direct /peer calls
        output = mgr.call(cli, task)
        if mgr.is_peer_error(output):
            error(f"Peer {cli.name} failed: {output}")
        elif output and len(output.strip()) > 10:
            summary = mgr.summarize_result(cli.name, output, task)
            history.append({"role": "user", "content": f"/peer {cli.name}: {task}"})
            history.append({"role": "assistant", "content": summary})
            success(f"Result from {cli.name} added to conversation context.")
        return True, history

    # ── /rag ─────────────────────────────────────────────────────────────────
    if low.startswith("/rag"):
        parts = cmd.split(maxsplit=1)
        if len(parts) < 2:
            info("Usage: /rag <prompt>   — show what the KB would inject for that prompt")
            return True, history

        from core.retrieval import retrieve_debug
        d = retrieve_debug(parts[1])

        console.print(f"\n[bold]RAG Debug[/bold] — query sent to KB: [cyan]\"{d['query']}\"[/cyan]")
        console.print(f"  Backend: [cyan]{d['backend']}[/cyan]   "
                      f"Score threshold: [cyan]{d.get('threshold', '?')}[/cyan]\n")

        all_chunks = d.get("all_chunks", [])
        kept_set   = {id(r) for r in d.get("kept_chunks", [])}

        if not all_chunks:
            if "error" in d:
                warning(f"KB unavailable: {d['error']}")
            else:
                info("No results — KB is empty or no match found.")
            return True, history

        console.print(f"[bold]All chunks returned ({len(all_chunks)}):[/bold]")
        for i, r in enumerate(all_chunks, 1):
            score  = r.get("score", 0)
            source = Path(r.get("source", "")).name or "?"
            text   = r.get("text", "").strip()
            kept   = id(r) in kept_set
            tag    = "[green]✓ kept[/green]" if kept else "[red]✗ filtered[/red]"
            console.print(f"\n  [{i}] {tag}  score=[cyan]{score:.3f}[/cyan]  source=[dim]{source}[/dim]")
            # Show first 3 lines of the chunk
            preview = "\n".join(text.splitlines()[:3])
            if len(text.splitlines()) > 3:
                preview += f"\n    [dim]... ({len(text.splitlines())} lines total)[/dim]"
            for line in preview.splitlines():
                console.print(f"      {line}")

        console.print(f"\n[bold]Block injected into prompt ({len(d['block'])} chars):[/bold]")
        if d["block"]:
            console.print(f"[dim]{d['block'][:1200]}[/dim]")
            if len(d["block"]) > 1200:
                console.print(f"[dim]  ... ({len(d['block'])} chars total)[/dim]")
        else:
            info("(nothing injected — all chunks filtered out or KB empty)")
        console.print()
        return True, history

    if low == "/help":
        console.print("""
[bold]File commands:[/bold]
  /read <file>           Load file into context
  /load <file|*.py|dir>  Load file, glob, or whole directory
  /unread <file>         Remove file from context
  /ignore <pattern>      Add pattern to .codeyignore
  /context               Show loaded files and sizes
  /diff [file]           Show what Codey-v2 changed (colored diff)
  /undo [file]           Restore file to previous version

[bold]Code Review (v2.5.2):[/bold]
  /review <file.py>      Run all linters + optional agent fix
  (auto-lint runs after every file write — no command needed)

[bold]Search:[/bold]
  /search <pattern>      Grep across all project files
  /search <pat> <dir>    Grep in specific directory

[bold]Git:[/bold]
  /git                   Show git status
  /git <message>         Stage all and commit
  /git push              Push to remote
  /git log               Show recent commits

[bold]Project:[/bold]
  /init                  Generate CODEY.md project memory
  /memory                Show CODEY.md contents
  /project               Show project info
  /cwd [path]            Show or change directory

[bold]Session:[/bold]
  /sessions              List all saved sessions
  /summarize             Compress conversation to save context
  /clear                 Clear history, context, undo, session
  /exit                  Save session and quit

[bold]Knowledge Base:[/bold]
  /rag <prompt>          Show what the KB would inject for that prompt

[bold]Learning:[/bold]
  /learning              Show learning system status (v2.2.0)

[bold]Voice (v2.5.1 — requires Termux:API):[/bold]
  /voice                 Show voice status and commands
  /voice on              Enable voice mode (TTS + STT)
  /voice off             Disable voice mode
  /voice listen          One-shot voice input → send to agent
  /voice rate <n>        Set TTS speed (default 1.0, range 0.1–4.0)
  /voice pitch <n>       Set TTS pitch (default 1.0)
  /voice speak <text>    Test TTS with given text
  (In voice mode, press Enter on a blank line to speak your task)

[bold]Peer CLIs:[/bold]
  /peer                  List available peer CLIs
  /peer <name> <task>    Call a specific CLI (claude/gemini/copilot/qwen)
  /peer <task>           Auto-pick best CLI for the task

[bold]CLI flags:[/bold]
  codey-v2 "task"              One-shot
  codey-v2 --chat "task"       Chat with prefilled prompt
  codey-v2 --yolo "task"       Skip all confirmations
  codey-v2 --fix file.py       Run file, auto-fix any errors
  codey-v2 --read file.py      Pre-load file into context
  codey-v2 --init              Generate CODEY.md and exit
  codey-v2 --no-resume         Start fresh (ignore saved session)
  codey-v2 --allow-self-mod    Enable self-modification (with checkpoints)
  codey-v2 --no-peer          Disable peer CLI escalation

[bold]Fine-tuning (v2.3.0):[/bold]
  codey-v2 --finetune          Export fine-tuning dataset + Colab notebook
  codey-v2 --finetune --ft-days 30 --ft-quality 0.7 --ft-model both
  codey-v2 --import-lora /path/to/adapter --lora-model primary

[bold]Environment variables:[/bold]
  ALLOW_SELF_MOD=1             Enable self-modification (alternative to flag)
  CODEY_MODEL                  Override model path
  CODEY_THREADS                Override thread count
        """)
        return True, history

    return False, history

def repl(initial_prompt=None, yolo=False, one_shot=False, preload=None, plan=False, no_plan=False, session_path=None, no_resume=False):
    console.print(BANNER)
    separator()

    # Start system monitor (background thread — also updates terminal title)
    monitor = get_monitor()
    monitor.start()

    # v2: Use loader_v2 to ensure model is available
    loader = get_loader()
    loader.load_primary()

    from core.project import detect_project
    from core.codeymd import find_codeymd
    proj = detect_project()
    if proj["type"] != "unknown":
        info(f"Project: [bold]{proj['type']}[/bold] · {os.getcwd()}")
    if find_codeymd():
        info("Memory: [bold]CODEY.md[/bold] found")
    else:
        info("No CODEY.md — run [bold]/init[/bold] to create project memory")

    if preload:
        for f in preload:
            ctx.load_file(f)

    # Load saved session
    from core.sessions import load_session, save_session
    history = []
    if not no_resume:
        if session_path:
            history = load_session(path=session_path)
        else:
            history = load_session()  # auto-resume from cwd-based session file

    if initial_prompt and one_shot:
        try:
            response, history = _run_with_plan(initial_prompt, history, yolo, False, no_plan)
            # Display the response for one-shot mode
            if response and not response.startswith("["):
                if was_last_streamed():
                    separator()
                else:
                    separator()
                    console.print(f"\n[bold green]Codey-v2:[/bold green] {response}")
                    separator()
            save_session(history)
        except KeyboardInterrupt:
            pass
        finally:
            shutdown()
        return

    info("Type your task. /help for commands.")
    separator()

    if initial_prompt:
        try:
            response, history = _run_with_plan(initial_prompt, history, yolo, plan, no_plan)
            # Display the response
            if response and not response.startswith("["):
                if was_last_streamed():
                    separator()
                else:
                    separator()
                    console.print(f"\n[bold green]Codey-v2:[/bold green] {response}")
                    separator()
            save_session(history)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")

    while True:
        loaded = ctx.list_loaded()
        file_hint = f" ({len(loaded)} file{'s' if len(loaded)!=1 else ''})" if loaded else ""
        try:
            # Use plain input() instead of Rich console.input() —
            # Rich's input conflicts with raw sys.stdout.write() used
            # during streaming, causing the REPL to hang after responses.
            user_input = input(f"\033[1;34mYou{file_hint}>\033[0m ").strip()
            # Paste detection: terminal pastes arrive as multiple buffered lines.
            # Drain any immediately-available continuation lines and join them
            # so a multi-line paste is treated as one message, not many short ones.
            try:
                import select as _sel
                _extra = []
                while _sel.select([sys.stdin], [], [], 0.02)[0]:
                    _line = sys.stdin.readline().rstrip('\n').strip()
                    if _line:
                        _extra.append(_line)
                if _extra:
                    user_input = user_input + ' ' + ' '.join(_extra)
            except Exception:
                pass  # select unavailable — proceed with single line
        except (KeyboardInterrupt, EOFError):
            save_session(history)
            print("\nSession saved. Goodbye!")
            shutdown()
            break
        except Exception as e:
            # Handle any terminal input errors gracefully
            error(f"Input error: {e}")
            save_session(history)
            print("\nSession saved. Exiting...")
            shutdown()
            break

        if not user_input:
            # In voice mode: blank input → trigger STT
            try:
                from core.voice import get_voice as _get_voice
                _v = _get_voice()
                if _v.enabled and _v.stt_available():
                    spoken = _v.listen()
                    if spoken:
                        user_input = spoken
                    else:
                        continue
                else:
                    continue
            except Exception:
                continue

        # ── Stats bar after input ──────────────────────────────────────────
        console.print(monitor.render())

        was_cmd, history = handle_command(user_input, history, yolo=yolo)
        if was_cmd:
            continue

        try:
            response, history = _run_with_plan(user_input, history, yolo, plan, no_plan)
            # Display the response if it's not a tool execution result
            if response and not response.startswith("["):
                if was_last_streamed():
                    separator()
                else:
                    separator()
                    console.print(f"\n[bold green]Codey-v2:[/bold green] {response}")
                    separator()
                # Speak the response if voice mode is on (Ctrl+C to interrupt)
                try:
                    from core.voice import get_voice as _get_voice
                    _v = _get_voice()
                    if _v.enabled and _v.tts_available():
                        try:
                            _v.speak(response)
                        except KeyboardInterrupt:
                            _v.stop_speaking()
                            console.print("[dim]Speech interrupted.[/dim]")
                except Exception:
                    pass
            save_session(history)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except SystemExit:
            # Allow clean exit
            raise
        except Exception as e:
            error(f"Agent error: {e}")
            import traceback
            traceback.print_exc()
            # Continue the REPL even after errors
            console.print("\n[dim]An error occurred. You can continue chatting.[/dim]")

def main():
    args = parse_args()

    if args.version:
        print(f"Codey-v2 v{CODEY_VERSION}")
        sys.exit(0)

    apply_overrides(args)

    # Daemon mode (v2 feature)
    if args.daemon:
        from core.daemon import Daemon, check_pid_file
        if check_pid_file():
            error("Daemon is already running. Use --daemon-stop to shut it down.")
            sys.exit(1)
        info("Starting Codey-v2 daemon mode...")
        daemon = Daemon()
        daemon.run()
        return

    if args.clear_session:
        from core.sessions import clear_session
        clear_session()
        return

    if args.init:
        loader = get_loader()
        loader.load_primary()
        run_init()
        shutdown()
        return

    if args.tdd:
        loader = get_loader()
        loader.load_primary()
        from core.tdd import run_tdd_loop, find_test_file
        test_file = args.tests or find_test_file(args.tdd)
        if not test_file:
            # Suggest test file name
            from pathlib import Path as _P
            suggested = "test_" + _P(args.tdd).name
            error(f"No test file found. Create {suggested} or use: codey-v2 --tdd {args.tdd} --tests {suggested}")
            shutdown()
            return
        run_tdd_loop(args.tdd, test_file, yolo=args.yolo)
        shutdown()
        return

    if args.fix:
        loader = get_loader()
        loader.load_primary()
        from core.fixmode import fix_file
        # --fix is automated, always disable confirmations
        from utils import config
        config.AGENT_CONFIG["confirm_write"] = False
        config.AGENT_CONFIG["confirm_shell"] = False
        fix_file(args.fix, extra_instruction=args.prompt or "", yolo=True)
        shutdown()
        return

    # Fine-tuning data export (v2.3.0)
    if args.finetune:
        from core.finetune_prep import prepare_finetune_data
        info("Preparing fine-tuning dataset...")
        results = prepare_finetune_data(
            days=args.ft_days,
            min_quality=args.ft_quality,
            model_variant=args.ft_model,
            output_dir=args.ft_output
        )
        if "error" in results:
            error(results["error"])
            sys.exit(1)
        shutdown()
        return

    # LoRA adapter import (v2.3.0)
    if args.import_lora:
        from core.lora_import import import_lora_adapter
        info(f"Importing LoRA adapter from {args.import_lora}...")
        results = import_lora_adapter(
            adapter_path=args.import_lora,
            model_variant=args.lora_model,
            quantize=args.lora_quant,
            merge_on_device=args.lora_merge
        )
        if results.get("success"):
            success(f"LoRA adapter imported: {results.get('model_path')}")
            if results.get("backup_path"):
                info(f"Backup created: {results['backup_path']} (use --rollback to restore)")
        else:
            error(f"Import failed: {results.get('error', 'Unknown error')}")
            if results.get("instructions"):
                print(results["instructions"])
            sys.exit(1)
        shutdown()
        return

    resolved_session = None
    if hasattr(args, "session") and args.session and args.session != "list":
        from pathlib import Path as _P
        from core.sessions import SESSIONS_DIR
        matches = list(_P(SESSIONS_DIR).glob(f"*{args.session}*.json"))
        if matches:
            resolved_session = str(matches[0])
            info(f"Resuming: {matches[0].name}")

    one_shot = bool(args.prompt and not args.chat)
    repl(
        initial_prompt=args.prompt,
        yolo=args.yolo,
        one_shot=one_shot,
        preload=args.read,
        session_path=resolved_session,
        plan=args.plan,
        no_plan=args.no_plan,
        no_resume=args.no_resume,
    )

if __name__ == "__main__":
    main()
