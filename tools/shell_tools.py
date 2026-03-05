import subprocess
from utils.logger import warning, confirm as ask_confirm
from utils.config import AGENT_CONFIG

# Commands that always require confirmation unless in YOLO mode
DANGEROUS_COMMANDS = [
    "rm", "rmdir", "mkfs", "dd", "chmod", "wget", "curl", "mv", "cp",
]

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

def shell(command: str, yolo: bool = False, timeout: int = 30) -> str:
    """
    Execute a shell command. Returns combined stdout + stderr.
    Prompts for confirmation on dangerous or any command if confirm_shell=True.
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
    """Use find to search for files matching pattern."""
    cmd = f'find {path} -name "{pattern}" 2>/dev/null | head -50'
    return shell(cmd, yolo=True)
