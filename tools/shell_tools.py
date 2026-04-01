import subprocess
from pathlib import Path
from utils.logger import warning, confirm as ask_confirm, error
from utils.config import AGENT_CONFIG

# Commands that always require an explicit warning + confirmation
DANGEROUS_COMMANDS = [
    "rm", "rmdir", "mkfs", "dd", "chmod", "wget", "curl", "mv", "cp",
]

def is_dangerous(command: str) -> bool:
    cmd_parts = command.split()
    if not cmd_parts:
        return False
    base_cmd = Path(cmd_parts[0]).name
    if base_cmd in DANGEROUS_COMMANDS:
        return True
    cmd_lower = command.lower()
    dangerous_patterns = [
        "sudo ", "> /dev/", "| sh", "| bash", ":(){:|:&};:",
        # Indirect execution via sh/bash -c
        "sh -c ", "bash -c ",
        # Destructive git operations
        "reset --hard", "push --force", "push -f ",
        # find -delete
        " -delete",
    ]
    return any(p in cmd_lower for p in dangerous_patterns)

def shell(command: str, yolo: bool = False, timeout: int = 1800) -> str:
    """
    Execute a shell command. Returns combined stdout + stderr.

    All commands go through the user confirmation path when confirm_shell=True
    (the default). Metacharacter commands (&&, |, ;, etc.) are allowed — the
    user sees the full command before approving.  Dangerous destructive commands
    (rm, curl, etc.) receive an explicit warning before the confirmation prompt.

    Args:
        command: The shell command to execute
        yolo: Skip confirmation prompts
        timeout: Command timeout in seconds (default: 30 minutes)

    Returns:
        Command output or error message
    """
    should_confirm = False

    if is_dangerous(command):
        warning(f"Potentially dangerous command: `{command}`")
        should_confirm = True
    elif AGENT_CONFIG["confirm_shell"] and not yolo:
        should_confirm = True

    if should_confirm and not yolo:
        if not ask_confirm(f"Run shell command: `{command}`?"):
            return "[CANCELLED] User declined to run command."

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output.strip() if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Command timed out after {timeout}s"
    except Exception as e:
        return f"[ERROR] {e}"

def search_files(pattern: str, path: str = ".") -> str:
    """Search for files matching pattern. Uses subprocess list args to prevent injection."""
    try:
        result = subprocess.run(
            ["find", path, "-name", pattern],
            capture_output=True, text=True, timeout=15
        )
        lines = (result.stdout + result.stderr).strip().splitlines()
        lines = [l for l in lines if l.strip()][:50]
        return "\n".join(lines) if lines else "(no matches)"
    except subprocess.TimeoutExpired:
        return "[ERROR] Search timed out"
    except FileNotFoundError:
        return "[ERROR] 'find' command not available"
    except Exception as e:
        return f"[ERROR] {e}"
