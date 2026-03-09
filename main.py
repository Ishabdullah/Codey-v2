#!/usr/bin/env python3
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import console, info, success, error, warning, separator
from utils.config import CODEY_VERSION
from core.loader_v2 import get_loader
from core.inference_v2 import infer
from core.agent import run_agent
from core import context as ctx

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

def shutdown():
    try:
        from core.inference_v2 import infer as infer_v2
        # stop_server is not needed in v2 - models are managed by loader_v2
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
        from core.githelper import git_commit, git_push, git_status, git_log, is_git_repo
        parts = cmd.split(maxsplit=1)

        if not is_git_repo():
            error("Not a git repository.")
            return True, history

        sub = parts[1].strip() if len(parts) > 1 else ""
        sub_low = sub.lower()

        if sub_low == "status" or sub == "":
            console.print(git_status())
        elif sub_low == "log":
            console.print(git_log())
        elif sub_low.startswith("push"):
            result = git_push()
            success(result) if not result.startswith("[ERROR]") else error(result)
        else:
            # Treat as commit message
            result = git_commit(sub)
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
  /clear                 Clear history, context, undo, session
  /exit                  Save session and quit

[bold]CLI flags:[/bold]
  codey-v2 "task"              One-shot
  codey-v2 --chat "task"       Chat with prefilled prompt
  codey-v2 --yolo "task"       Skip all confirmations
  codey-v2 --fix file.py       Run file, auto-fix any errors
  codey-v2 --read file.py      Pre-load file into context
  codey-v2 --init              Generate CODEY.md and exit
  codey-v2 --no-resume         Start fresh (ignore saved session)
  codey-v2 --allow-self-mod    Enable self-modification (with checkpoints)

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
            response, history = run_agent(initial_prompt, history, yolo=yolo, no_plan=no_plan)
            # Display the response for one-shot mode
            if response and not response.startswith("["):
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
            response, history = run_agent(initial_prompt, history, yolo=yolo, use_plan=plan, no_plan=no_plan)
            # Display the response
            if response and not response.startswith("["):
                separator()
                console.print(f"\n[bold green]Codey-v2:[/bold green] {response}")
                separator()
            save_session(history)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")

    while True:
        loaded = ctx.list_loaded()
        suffix = f" [bold dim]({len(loaded)} file{'s' if len(loaded)!=1 else ''})[/bold dim]" if loaded else ""
        try:
            user_input = console.input(f"[bold blue]You{suffix}>[/bold blue] ").strip()
        except (KeyboardInterrupt, EOFError):
            save_session(history)
            console.print("\n[dim]Session saved. Goodbye![/dim]")
            shutdown()
            break
        except Exception as e:
            # Handle any terminal input errors gracefully
            error(f"Input error: {e}")
            save_session(history)
            console.print("\n[dim]Session saved. Exiting...[/dim]")
            shutdown()
            break

        if not user_input:
            continue

        was_cmd, history = handle_command(user_input, history, yolo=yolo)
        if was_cmd:
            continue

        try:
            response, history = run_agent(user_input, history, yolo=yolo, use_plan=plan, no_plan=no_plan)
            # Display the response if it's not a tool execution result
            if response and not response.startswith("["):
                separator()
                console.print(f"\n[bold green]Codey-v2:[/bold green] {response}")
                separator()
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
