#!/usr/bin/env python3
import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import console, info, success, error, warning, separator
from utils.config import CODEY_VERSION
from core.loader import load_model
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
    parser = argparse.ArgumentParser(description="Codey - Local AI coding assistant")
    parser.add_argument("prompt",       nargs="?")
    parser.add_argument("--yolo",       action="store_true", help="Skip confirmations")
    parser.add_argument("--threads",    type=int)
    parser.add_argument("--ctx",        type=int)
    parser.add_argument("--version",    action="store_true")
    parser.add_argument("--chat",       action="store_true")
    parser.add_argument("--read",       nargs="+", metavar="FILE")
    parser.add_argument("--init",       action="store_true", help="Generate CODEY.md")
    parser.add_argument("--fix",        metavar="FILE", help="Run file, auto-fix errors")
    parser.add_argument("--no-resume",  action="store_true", help="Don't load saved session")
    parser.add_argument("--clear-session", action="store_true", help="Clear saved session")
    return parser.parse_args()

def apply_overrides(args):
    from utils import config
    if args.yolo:
        config.AGENT_CONFIG["confirm_shell"] = False
        config.AGENT_CONFIG["confirm_write"] = False
        info("YOLO mode: confirmations disabled.")
    if args.threads:
        config.MODEL_CONFIG["n_threads"] = args.threads
    if args.ctx:
        config.MODEL_CONFIG["n_ctx"] = args.ctx

def shutdown():
    try:
        from core.inference import stop_server
        stop_server()
    except Exception:
        pass

def run_init():
    from core.project import detect_project
    from core.codeymd import get_init_prompt, write_codeymd, find_codeymd
    from core.inference import infer
    existing = find_codeymd()
    if existing:
        warning(f"CODEY.md already exists at {existing}")
        ans = input("Overwrite? [y/N]: ").strip().lower()
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
            query_parts = parts[1].split(maxsplit=1)
            pattern = query_parts[0]
            search_path = query_parts[1] if len(query_parts) > 1 else "."
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
                if console.input("[dim]Push to remote? [y/N]: [/dim]").strip().lower() in ("y", "yes"):
                    push_result = git_push()
                    success(push_result) if not push_result.startswith("[ERROR]") else error(push_result)
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
        loaded = ctx.list_loaded()
        if loaded:
            console.print("[bold]Loaded files:[/bold]")
            for f in loaded:
                size = len(ctx._loaded_files.get(f, ""))
                console.print(f"  📄 {Path(f).name} ({size} chars)")
        else:
            info("No files loaded.")
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

    if low.startswith("/cwd"):
        parts = cmd.split(maxsplit=1)
        if len(parts) > 1:
            try:
                os.chdir(parts[1])
                from core.project import invalidate_cache
                invalidate_cache()
                success(f"Working directory: {os.getcwd()}")
            except Exception as e:
                error(str(e))
        else:
            info(f"Current directory: {os.getcwd()}")
        return True, history

    if low == "/help":
        console.print("""
[bold]File commands:[/bold]
  /read <file>           Load file into context
  /load <file|*.py|dir>  Load file, glob, or whole directory
  /unread <file>         Remove file from context
  /context               Show loaded files and sizes
  /diff [file]           Show what Codey changed (colored diff)
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
  codey "task"           One-shot
  codey --chat "task"    Chat with prefilled prompt
  codey --yolo "task"    Skip all confirmations
  codey --fix file.py    Run file, auto-fix any errors
  codey --read file.py   Pre-load file into context
  codey --init           Generate CODEY.md and exit
  codey --no-resume      Start fresh (ignore saved session)
        """)
        return True, history

    return False, history

def repl(initial_prompt=None, yolo=False, one_shot=False, preload=None, resume=True):
    console.print(BANNER)
    separator()
    load_model()

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
    from core.sessions import load_session, save_session, session_exists
    history = []
    if resume and session_exists():
        history = load_session()

    if initial_prompt and one_shot:
        try:
            _, history = run_agent(initial_prompt, history, yolo=yolo)
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
            _, history = run_agent(initial_prompt, history, yolo=yolo)
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

        if not user_input:
            continue

        was_cmd, history = handle_command(user_input, history, yolo=yolo)
        if was_cmd:
            continue

        try:
            _, history = run_agent(user_input, history, yolo=yolo)
            save_session(history)
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
        except Exception as e:
            error(f"Agent error: {e}")
            import traceback
            traceback.print_exc()

def main():
    args = parse_args()

    if args.version:
        print(f"Codey v{CODEY_VERSION}")
        sys.exit(0)

    apply_overrides(args)

    if args.clear_session:
        from core.sessions import clear_session
        clear_session()
        return

    if args.init:
        load_model()
        run_init()
        shutdown()
        return

    if args.fix:
        load_model()
        from core.fixmode import fix_file
        # --fix is automated, always disable confirmations
        from utils import config
        config.AGENT_CONFIG["confirm_write"] = False
        config.AGENT_CONFIG["confirm_shell"] = False
        fix_file(args.fix, extra_instruction=args.prompt or "", yolo=True)
        shutdown()
        return

    one_shot = bool(args.prompt and not args.chat)
    repl(
        initial_prompt=args.prompt,
        yolo=args.yolo,
        one_shot=one_shot,
        preload=args.read,
        resume=not args.no_resume,
    )

if __name__ == "__main__":
    main()
