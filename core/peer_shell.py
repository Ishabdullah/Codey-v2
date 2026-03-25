#!/usr/bin/env python3
"""
PTY-based peer CLI runner for Codey-v2.

Spawns a peer CLI (claude, gemini, qwen) directly inside Codey's
terminal window, automatically types the task prompt into it, and captures
the full response.

User interaction:
  - The peer CLI opens inline — you see everything live.
  - If the peer asks for approval (allow button, y/n, etc.), press ENTER
    to take over and respond, then press Ctrl+B to hand control back to Codey.
  - When the peer is finished, close it normally (/exit, Ctrl+D, /quit, etc.)
    — Codey reads the result automatically.

Requires: pip install pexpect
"""

import io
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from utils.logger import info, warning, separator

# How long to wait for each CLI to show its ready prompt before typing
CLI_READY_TIMEOUT = 6.0

# Patterns that indicate the CLI is ready to receive input (per CLI)
# pexpect.TIMEOUT is always the last fallback so we don't hang forever
CLI_READY_PATTERNS: dict = {}  # populated lazily to avoid pexpect import at module level

# ANSI colours
_CYAN  = "\033[1;36m"
_DIM   = "\033[2m"
_RESET = "\033[0m"
_RED   = "\033[31m"


def _terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 80


def _header(label: str, width: int) -> str:
    label = f" {label} "
    pad_l = (width - len(label)) // 2
    pad_r = width - pad_l - len(label)
    return "─" * pad_l + label + "─" * pad_r


class _LiveCapture:
    """Writes to stdout in real-time AND accumulates to a buffer.
    Handles both str and bytes from pexpect safely."""

    def __init__(self):
        self._buf = io.StringIO()

    def write(self, data):
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="replace")
        sys.stdout.write(data)
        sys.stdout.flush()
        self._buf.write(data)

    def flush(self):
        sys.stdout.flush()

    def getvalue(self) -> str:
        return self._buf.getvalue()


def _check_pexpect() -> bool:
    try:
        import pexpect  # noqa: F401
        return True
    except ImportError:
        return False


def run_peer(cli_name: str, cmd: str, prompt_text: str = "") -> str:
    """
    Open a peer CLI inside Codey's terminal, auto-type the prompt, capture output.

    Args:
        cli_name:    Short display name  (e.g. "copilot")
        cmd:         Shell command       (e.g. "copilot")
        prompt_text: Task to type automatically once the CLI is ready.

    Returns:
        Full captured output string (everything that appeared in the peer session).
    """
    if not _check_pexpect():
        warning("pexpect not installed — run: pip install pexpect")
        warning("Falling back to basic shell (no auto-typing).")
        return _run_basic_fallback(cli_name, cmd, prompt_text)

    import pexpect

    width   = _terminal_width()
    border  = "─" * width
    capture = _LiveCapture()

    # ── Draw opening border ────────────────────────────────────────────────
    print(f"\n{_CYAN}{_header(cli_name.upper() + ' CLI', width)}{_RESET}")
    info(f"Opening {cli_name} — task will be typed automatically.")
    if prompt_text:
        print(f"{_DIM}Task: {prompt_text[:120]}{'…' if len(prompt_text) > 120 else ''}{_RESET}")
    print(f"{_DIM}Ctrl+B → take over input | close {cli_name} normally when done{_RESET}")
    print(f"{_DIM}{border}{_RESET}\n")

    try:
        child = pexpect.spawn(
            cmd,
            encoding="utf-8",
            timeout=300,
            dimensions=(40, min(width, 220)),
        )
        child.logfile_read = capture   # everything child prints → stdout + buffer

        # ── Wait for CLI to initialise ────────────────────────────────────
        _wait_for_ready(child, cli_name, pexpect)

        # ── Auto-type the prompt ──────────────────────────────────────────
        if prompt_text:
            time.sleep(0.2)
            child.sendline(prompt_text)

        # ── Hand control to user (Ctrl+B = escape back to Codey) ─────────
        # interact() returns when:
        #   a) user presses the escape character (Ctrl+B → \x02), OR
        #   b) the child process exits (EOF)
        child.interact(escape_character="\x02")

        # ── Drain any last output, then close ────────────────────────────
        try:
            child.expect(pexpect.EOF, timeout=8)
        except (pexpect.EOF, pexpect.TIMEOUT):
            pass
        try:
            child.close(force=True)
        except Exception:
            pass

    except pexpect.exceptions.ExceptionPexpect as e:
        print(f"\n{_RED}[peer_shell] pexpect error: {e}{_RESET}")
    except FileNotFoundError:
        print(f"\n{_RED}[peer_shell] Command not found: {cmd}{_RESET}")
    except Exception as e:
        print(f"\n{_RED}[peer_shell] Unexpected error: {e}{_RESET}")

    # ── Draw closing border ────────────────────────────────────────────────
    print(f"\n{_DIM}{border}{_RESET}")
    print(f"{_CYAN}{_header(cli_name.upper() + ' DONE', width)}{_RESET}\n")
    info(f"Back in Codey — reading {cli_name} output…")

    return capture.getvalue()


def run_prompted(cli_name: str, cmd: str, flag: str, prompt_text: str) -> str:
    """
    Run a peer CLI in non-interactive mode by passing the prompt as a flag.
    e.g.  claude -p "write a function that reverses a string"

    Streams output live to the terminal and captures it for Codey.
    No TUI, no trust dialogs, no pexpect needed.
    """
    import subprocess
    width  = _terminal_width()
    border = "─" * width

    print(f"\n{_CYAN}{_header(cli_name.upper() + ' CLI  (direct)', width)}{_RESET}")
    info(f"Asking {cli_name}: {prompt_text[:100]}{'…' if len(prompt_text) > 100 else ''}")
    print(f"{_DIM}{border}{_RESET}\n")

    captured = []
    try:
        proc = subprocess.Popen(
            [cmd, flag, prompt_text],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            captured.append(line)
        proc.wait()
    except FileNotFoundError:
        print(f"{_RED}[peer_shell] Command not found: {cmd}{_RESET}")
    except Exception as e:
        print(f"{_RED}[peer_shell] Error: {e}{_RESET}")

    print(f"\n{_DIM}{border}{_RESET}")
    print(f"{_CYAN}{_header(cli_name.upper() + ' DONE', width)}{_RESET}\n")
    info(f"Back in Codey — reading {cli_name} output…")
    return "".join(captured)


def run_positional(cli_name: str, cmd: str, prompt_text: str) -> str:
    """
    Run a multi-word CLI command where the prompt is a positional argument.
    e.g.  gh copilot suggest "write a function that reverses a string"

    The cmd string is split into argv parts and the prompt is appended as the
    final argument.  Streams output live and captures it for Codey.
    """
    import subprocess
    width  = _terminal_width()
    border = "─" * width

    argv = cmd.split() + [prompt_text]
    print(f"\n{_CYAN}{_header(cli_name.upper() + ' CLI  (direct)', width)}{_RESET}")
    info(f"Asking {cli_name}: {prompt_text[:100]}{'…' if len(prompt_text) > 100 else ''}")
    print(f"{_DIM}{border}{_RESET}\n")

    captured = []
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "CI": "true", "NO_COLOR": "1"},
        )
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            captured.append(line)
        proc.wait()
    except FileNotFoundError:
        print(f"{_RED}[peer_shell] Command not found: {argv[0]}{_RESET}")
    except Exception as e:
        print(f"{_RED}[peer_shell] Error: {e}{_RESET}")

    print(f"\n{_DIM}{border}{_RESET}")
    print(f"{_CYAN}{_header(cli_name.upper() + ' DONE', width)}{_RESET}\n")
    info(f"Back in Codey — reading {cli_name} output…")
    return "".join(captured)


def run_direct(cli_name: str, cmd: str, prompt_text: str = "") -> str:
    """
    Run a peer CLI directly in the real terminal (no nested PTY).
    Used for CLIs that bundle their own native PTY module
    and crash when spawned inside pexpect's PTY.

    Output is captured via the `script` utility so Codey can read it.
    The prepared prompt is shown above the CLI so you can paste it in.
    """
    import tempfile
    width   = _terminal_width()
    border  = "─" * width
    outfile = tempfile.mktemp(prefix="codey_peer_", suffix=".txt")

    print(f"\n{_CYAN}{_header(cli_name.upper() + ' CLI', width)}{_RESET}")
    info(f"Opening {cli_name} in your terminal.")

    if prompt_text:
        print(f"\n{_DIM}── Paste this into {cli_name} ──────────────────────────{_RESET}")
        print(f"{prompt_text}")
        print(f"{_DIM}{border}{_RESET}\n")

    info(f"Close {cli_name} normally when done (/exit, Ctrl+D, /quit…)")
    print(f"{_DIM}Ctrl+B → return to Codey at any point{_RESET}\n")

    # `script -q -c <cmd> <file>` records the session to outfile
    # while letting the CLI run in the real terminal with full PTY support.
    # -q = quiet (no "Script started/done" lines)
    os.system(f'script -q -c "{cmd}" "{outfile}"')

    print(f"\n{_DIM}{border}{_RESET}")
    print(f"{_CYAN}{_header(cli_name.upper() + ' DONE', width)}{_RESET}\n")
    info(f"Back in Codey — reading {cli_name} output…")

    try:
        raw = Path(outfile).read_bytes()
        Path(outfile).unlink(missing_ok=True)
        # Strip ANSI escape codes from the recorded script output
        text = raw.decode("utf-8", errors="replace")
        text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
        text = re.sub(r"\x1b\][^\x07]*\x07", "", text)
        return text
    except Exception as e:
        return f"[Could not read output: {e}]"


def _wait_for_ready(child, cli_name: str, pexpect_mod) -> None:
    """
    Wait for the CLI to show its ready/welcome state before we type.
    Handles per-CLI quirks (e.g. Claude's workspace trust dialog).
    """
    if cli_name == "claude":
        _wait_for_claude(child, pexpect_mod)
    else:
        patterns_map = {
            "gemini": [r">\s*$", r"\?\s*$"],
            "qwen":   [r">\s*$", r"\$\s*$"],
        }
        patterns = patterns_map.get(cli_name, [])
        patterns.append(pexpect_mod.TIMEOUT)
        try:
            child.expect(patterns, timeout=CLI_READY_TIMEOUT)
        except (pexpect_mod.TIMEOUT, pexpect_mod.EOF):
            pass

    time.sleep(0.5)


def _wait_for_claude(child, pexpect_mod) -> None:
    """
    Handle Claude Code's startup sequence:
      1. Optional workspace trust dialog  → press Enter to accept
      2. Wait for the ❯ chat prompt
    """
    TRUST_PATTERNS = [
        "Quick safety check",
        "Is this a project you",
        "trust",
    ]
    READY_PATTERNS = [
        r"❯\s",
        r"❯$",
        r">\s*$",
        pexpect_mod.TIMEOUT,
    ]

    # Phase 1 — wait for either the trust dialog or the ready prompt
    try:
        idx = child.expect(
            TRUST_PATTERNS + READY_PATTERNS,
            timeout=12,
        )
        hit_trust = idx < len(TRUST_PATTERNS)
    except (pexpect_mod.TIMEOUT, pexpect_mod.EOF):
        hit_trust = False

    if hit_trust:
        # Accept the trust dialog with Enter and wait for the chat prompt
        time.sleep(0.4)
        child.sendline("")
        try:
            child.expect(READY_PATTERNS, timeout=10)
        except (pexpect_mod.TIMEOUT, pexpect_mod.EOF):
            pass

    # Phase 2 — give the UI a moment to finish rendering
    time.sleep(0.8)


def _run_basic_fallback(cli_name: str, cmd: str, prompt_text: str) -> str:
    """
    Fallback when pexpect is not installed.
    Opens CLI with tee capture; user must type the prompt manually.
    """
    import tempfile
    width  = _terminal_width()
    outfile = tempfile.mktemp(prefix="codey_peer_", suffix=".txt")

    print(f"\n{_CYAN}{_header(cli_name.upper() + ' CLI  (manual mode)', width)}{_RESET}")
    if prompt_text:
        print(f"\n{_DIM}── Paste this into {cli_name} ──{_RESET}")
        print(f"{_DIM}{prompt_text}{_RESET}")
        print(f"{_DIM}{'─' * width}{_RESET}\n")

    os.system(f'{cmd} 2>&1 | tee "{outfile}"')

    print(f"\n{_CYAN}{_header(cli_name.upper() + ' DONE', width)}{_RESET}\n")
    info(f"Reading {cli_name} output…")

    try:
        import pathlib
        out = pathlib.Path(outfile).read_text(encoding="utf-8", errors="replace")
        pathlib.Path(outfile).unlink(missing_ok=True)
        return out
    except Exception:
        return ""
