#!/usr/bin/env python3
"""
Peer CLI escalation for Codey-v2.

When Codey exhausts its retry budget on a task, it can escalate to an
external AI coding CLI: Claude Code, Gemini CLI, GitHub Copilot CLI, or Qwen CLI.

Flow:
  1. Codey hits max retries on a task
  2. PeerCLIManager selects best CLI for the task type
  3. Rich confirmation prompt — user can approve, deny, redirect, or pick different CLI
  4. Approved: CLI runs in the foreground terminal (user can interact live)
     All output is captured to a temp file via `tee`
  5. When CLI exits, Codey reads captured output and summarizes
  6. Work continues with the result as context
"""

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import info, warning, success, error, separator


@dataclass
class PeerCLI:
    name: str
    description: str
    cmd: str            # base shell command
    check_cmd: str      # command to test if installed
    strengths: List[str]
    interactive: bool = True   # True = open full interactive session
    prompt_flag: str = ""      # flag for non-interactive prompt injection
    prompt_prefix: str = ""    # prefix before the prompt string
    use_pty: bool = True       # False = run via os.system (avoids nested PTY issues)


# ── Registry ──────────────────────────────────────────────────────────────────

PEER_REGISTRY: List[PeerCLI] = [
    PeerCLI(
        name="claude",
        description="Claude Code (Anthropic)",
        cmd="claude",
        check_cmd="claude --version",
        strengths=["debugging", "refactor", "architecture", "complex", "review"],
        interactive=False,
        use_pty=False,
        prompt_flag="-p",   # claude -p "task" → non-interactive, clean output
    ),
    PeerCLI(
        name="gemini",
        description="Gemini CLI (Google)",
        cmd="gemini",
        check_cmd="gemini --version",
        strengths=["explain", "analysis", "large_context", "review", "generate"],
        interactive=False,
        use_pty=False,
        prompt_flag="-p",
    ),
    PeerCLI(
        name="qwen",
        description="Qwen CLI",
        cmd="qwen",
        check_cmd="qwen --version",
        strengths=["generate", "code", "completion", "quick_fix"],
        interactive=False,
        use_pty=False,
        prompt_flag="-p",
    ),
]

# Task type → preferred CLI order (first available wins)
TASK_CLI_PREFERENCE: Dict[str, List[str]] = {
    "debugging":  ["claude", "gemini", "qwen"],
    "refactor":   ["claude", "gemini", "qwen"],
    "generate":   ["qwen", "claude", "gemini"],
    "review":     ["gemini", "claude", "qwen"],
    "explain":    ["gemini", "claude", "qwen"],
    "complex":    ["claude", "gemini", "qwen"],
    "default":    ["claude", "gemini", "qwen"],
}


# ── Manager ───────────────────────────────────────────────────────────────────

class PeerCLIManager:
    """Manages escalation to external AI coding CLIs."""

    def __init__(self):
        self._available: Optional[List[PeerCLI]] = None

    def available(self) -> List[PeerCLI]:
        """Return cached list of installed peer CLIs."""
        if self._available is None:
            self._available = [c for c in PEER_REGISTRY if self._is_installed(c)]
        return self._available

    def _is_installed(self, cli: PeerCLI) -> bool:
        # shutil.which is the most reliable check — works even if
        # the CLI doesn't support --version or returns non-zero for it
        base_cmd = cli.cmd.split()[0]
        if not shutil.which(base_cmd):
            return False
        # For CLIs that bundle native node modules (e.g. node-pty), do a quick
        # smoke-test to catch platforms where the binary exists but crashes on
        # start (e.g. copilot on Android ARM64 missing pty.node prebuilds).
        if cli.check_cmd:
            try:
                result = subprocess.run(
                    cli.check_cmd.split(),
                    capture_output=True, timeout=5
                )
                stderr = (result.stderr or b"").decode("utf-8", errors="replace")
                # Detect node native-module crash signatures
                native_crash = any(sig in stderr for sig in [
                    "Failed to load native module",
                    "pty.node",
                    "prebuilds/",
                    "NODE_MODULE_VERSION",
                ])
                return not native_crash
            except FileNotFoundError:
                return False
            except Exception:
                return False
        return True

    def detect_task_type(self, user_message: str, errors: List[str]) -> str:
        """Infer task type from the user message and accumulated error log."""
        msg = user_message.lower()
        err_text = " ".join(errors).lower()
        if any(k in msg for k in ["fix", "bug", "error", "broken", "crash", "fail", "debug"]):
            return "debugging"
        if any(k in msg for k in ["refactor", "rewrite", "restructure", "clean up"]):
            return "refactor"
        if any(k in msg for k in ["explain", "what does", "how does", "why does"]):
            return "explain"
        if any(k in msg for k in ["review", "audit", "analyze", "analyse", "check"]):
            return "review"
        if any(k in msg for k in ["create", "write", "build", "generate", "make", "implement"]):
            return "generate"
        if any(k in err_text for k in ["traceback", "syntaxerror", "error:", "failed"]):
            return "debugging"
        return "default"

    def select_cli(self, task_type: str, exclude: List[str] = None) -> Optional[PeerCLI]:
        """
        Pick the best available CLI for the task type.
        Falls back through preference list, skipping excluded names.
        """
        exclude = exclude or []
        available_names = {c.name for c in self.available()}
        preference = TASK_CLI_PREFERENCE.get(task_type, TASK_CLI_PREFERENCE["default"])
        for name in preference:
            if name not in exclude and name in available_names:
                return next(c for c in self.available() if c.name == name)
        return None

    def build_prompt(self, user_message: str, errors: List[str], files: List[str]) -> str:
        """Build a context-rich prompt to pass to the external CLI."""
        lines = [f"I need help with the following task: {user_message}"]
        if files:
            lines.append(f"\nRelevant files: {', '.join(f for f in files if f)}")
        if errors:
            lines.append("\nPrevious attempts by Codey-v2 failed with these errors:")
            for e in errors[-3:]:
                lines.append(f"  • {e[:300]}")
        lines.append("\nPlease help resolve this.")
        return "\n".join(lines)

    def confirm(
        self,
        cli: PeerCLI,
        task_type: str,
        user_message: str,
    ) -> Tuple:
        """
        Show the escalation confirmation prompt.

        Returns one of:
          (True,       None)         — proceed with suggested CLI
          (False,      None)         — skip escalation
          ("switch",   cli_name)     — user wants a specific different CLI
          ("redirect", instruction)  — user gave Codey a new instruction
        """
        from utils.logger import console
        available_names = [c.name for c in self.available()]
        others = [n for n in available_names if n != cli.name]

        separator()
        console.print("\n[bold yellow]  ⚠  Codey hit max retries and needs help.[/bold yellow]")
        console.print(f"  Task:       [dim]{user_message[:80]}{'…' if len(user_message) > 80 else ''}[/dim]")
        console.print(f"  Suggest:    [bold cyan]{cli.description}[/bold cyan]  [dim]({task_type} task)[/dim]")
        if others:
            console.print(f"  Fallbacks:  [dim]{', '.join(others)}[/dim]")
        console.print()
        console.print("  [bold]Your options:[/bold]")
        console.print(f"    [green]y / enter[/green]          Call {cli.description}")
        console.print(f"    [red]n[/red]                  Skip — return control to you")
        if others:
            console.print(f"    [cyan]{' | '.join(others)}[/cyan]"
                          f"{'':>4}Use that CLI instead")
        console.print(f"    [cyan]<any text>[/cyan]         Tell Codey to try differently\n")

        try:
            ans = console.input("  → ").strip()
        except (EOFError, KeyboardInterrupt):
            return False, None

        if not ans or ans.lower() in ("y", "yes"):
            return True, None
        if ans.lower() in ("n", "no"):
            return False, None
        # Check if the answer is a known CLI name
        by_name = {c.name: c for c in self.available()}
        if ans.lower() in by_name:
            return "switch", ans.lower()
        # Otherwise treat as a redirect instruction to Codey
        return "redirect", ans

    def call(self, cli: PeerCLI, prompt: str) -> str:
        """
        Open the peer CLI inside Codey's terminal via a PTY, auto-type the
        prompt, let the user interact freely, capture everything it outputs.
        Returns the full captured output as a string.
        """
        from core.peer_shell import run_peer, run_direct, run_prompted
        if cli.prompt_flag and prompt:
            # Non-interactive: cmd -p "task" — clean output, no TUI
            return run_prompted(cli.name, cli.cmd, cli.prompt_flag, prompt)
        elif cli.use_pty:
            return run_peer(cli.name, cli.cmd, prompt)
        else:
            return run_direct(cli.name, cli.cmd, prompt)

    def summarize_result(self, cli_name: str, output: str, original_task: str) -> str:
        """Package the peer CLI output for injection into Codey's context."""
        if not output or len(output.strip()) < 10:
            return f"[Peer: {cli_name} produced no readable output]"
        preview = output[:2000].strip()
        return (
            f"[Peer CLI — {cli_name}]\n"
            f"Task: {original_task[:120]}\n"
            f"Output:\n{preview}"
            + ("\n… [truncated]" if len(output) > 2000 else "")
        )


# ── Singleton + entry point ────────────────────────────────────────────────────

_manager: Optional[PeerCLIManager] = None


def get_peer_cli_manager() -> PeerCLIManager:
    global _manager
    if _manager is None:
        _manager = PeerCLIManager()
    return _manager


def escalate(
    user_message: str,
    errors: List[str],
    files: List[str],
) -> Optional[str]:
    """
    Top-level escalation entry point. Called by agent when retries are exhausted.

    Returns:
      - Summary string to inject into agent context   (peer ran successfully)
      - "[redirect]: <instruction>"                    (user wants Codey to try differently)
      - None                                           (user skipped / no CLIs available)
    """
    mgr = get_peer_cli_manager()

    if not mgr.available():
        warning(
            "No peer CLIs found. Install claude / gemini / gh copilot / qwen "
            "to enable escalation."
        )
        return None

    task_type = mgr.detect_task_type(user_message, errors)
    excluded: List[str] = []

    while True:
        cli = mgr.select_cli(task_type, exclude=excluded)
        if not cli:
            warning("No more peer CLIs available to try.")
            return None

        result, payload = mgr.confirm(cli, task_type, user_message)

        if result is False:
            info("Peer CLI escalation skipped.")
            return None

        if result == "switch":
            by_name = {c.name: c for c in mgr.available()}
            cli = by_name.get(payload)
            if not cli:
                warning(f"CLI '{payload}' is not available.")
                excluded.append(payload)
                continue
            result = True  # fall through to call

        if result == "redirect":
            return f"[redirect]: {payload}"

        if result is True:
            prompt = mgr.build_prompt(user_message, errors, files)
            output = mgr.call(cli, prompt)
            summary = mgr.summarize_result(cli.name, output, user_message)
            success(f"Peer CLI ({cli.name}) done — Codey is reading the result…")
            return summary

        # Shouldn't reach here, but skip and try next
        excluded.append(cli.name)
