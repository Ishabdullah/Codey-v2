import subprocess
from pathlib import Path
from utils.logger import warning, confirm as ask_confirm, error
from utils.config import AGENT_CONFIG

# Commands that always require confirmation unless in YOLO mode
DANGEROUS_COMMANDS = [
    "rm", "rmdir", "mkfs", "dd", "chmod", "wget", "curl", "mv", "cp",
]

# Shell metacharacters that enable sub-shell injection
SHELL_METACHARACTERS = [';', '&&', '||', '|', '`', '$(', '${', '<(', '>(']

def validate_command_structure(command: str) -> tuple[bool, str]:
    """
    Validate command structure to prevent sub-shell injection.
    
    Checks for dangerous shell metacharacters that could enable:
    - Command chaining (;, &&, ||)
    - Piping to other commands (|)
    - Command substitution (``, $(), ${})
    - Process substitution (<(), >())
    
    Args:
        command: The shell command to validate
        
    Returns:
        Tuple of (is_valid, error_message)
        If valid: (True, "")
        If invalid: (False, "description of blocked pattern")
    """
    for char in SHELL_METACHARACTERS:
        if char in command:
            return False, f"Shell metacharacter '{char}' not allowed (prevents injection)"
    return True, ""

def is_dangerous(command: str) -> bool:
    cmd_parts = command.split()
    if not cmd_parts:
        return False
    # Check if the primary command is in our list
    base_cmd = Path(cmd_parts[0]).name
    if base_cmd in DANGEROUS_COMMANDS:
        return True
    # Still check for dangerous patterns like pipe to sh
    cmd_lower = command.lower()
    dangerous_patterns = ["sudo ", "> /dev/", "| sh", "| bash", ":(){:|:&};:"]
    return any(p in cmd_lower for p in dangerous_patterns)

def shell(command: str, yolo: bool = False, timeout: int = 1800, skip_structure_check: bool = False) -> str:
    """
    Execute a shell command. Returns combined stdout + stderr.
    Prompts for confirmation on dangerous or any command if confirm_shell=True.

    Args:
        command: The shell command to execute
        yolo: Skip confirmation prompts
        timeout: Command timeout in seconds (default: 30 minutes for long-running tasks)
        skip_structure_check: Skip shell metacharacter validation (for trusted callers)
        
    Returns:
        Command output or error message
    """
    # Validate command structure (prevent sub-shell injection)
    if not skip_structure_check:
        is_valid, error_msg = validate_command_structure(command)
        if not is_valid:
            error(f"Blocked unsafe command: `{command}`")
            return f"[ERROR] Command blocked: {error_msg}"
    
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
