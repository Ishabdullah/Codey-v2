"""
--fix mode: run a Python file, capture the error, auto-patch it.
codey --fix script.py
codey --fix script.py "also add argument parsing while you're at it"
"""
import subprocess
import sys
from pathlib import Path
from utils.logger import info, success, error, warning, separator
from utils.config import MODEL_CONFIG

def run_and_capture(path: str) -> tuple[bool, str]:
    """
    Run a Python file and capture output + errors.
    Returns (success, output_string).
    """
    try:
        result = subprocess.run(
            ["python3", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr or result.stdout
    except subprocess.TimeoutExpired:
        return False, "[ERROR] Script timed out after 30s"
    except Exception as e:
        return False, f"[ERROR] {e}"

def fix_file(filepath: str, extra_instruction: str = "", yolo: bool = False):
    """
    Main fix mode entrypoint.
    1. Read the file
    2. Run it and capture error
    3. If error, ask Codey to fix it
    4. Write the fix
    5. Re-run to verify
    """
    from core.agent import run_agent
    from core.context import load_file

    p = Path(filepath).expanduser()
    if not p.exists():
        error(f"File not found: {filepath}")
        return

    # Override confirmations in fix mode
    if yolo:
        from utils import config
        config.AGENT_CONFIG["confirm_write"] = False
        config.AGENT_CONFIG["confirm_shell"] = False

    info(f"Running {p.name}...")
    ok, output = run_and_capture(str(p))

    if ok:
        success(f"{p.name} ran successfully:")
        print(output)
        if extra_instruction:
            info(f"Applying extra instruction: {extra_instruction}")
            load_file(str(p))
            history = []
            run_agent(
                f"File {p.name} runs fine. Now: {extra_instruction}",
                history, yolo=yolo
            )
        return

    # Error — show it and auto-fix
    warning(f"Error in {p.name}:")
    print(output)
    separator()
    info("Auto-fixing...")

    # Load the broken file into context
    load_file(str(p))

    # Build fix prompt
    prompt = (
        f"The file {p.name} has an error. Fix it.\n\n"
        f"Error output:\n{output}\n\n"
        f"The file contents are in your context above. "
        f"Write the complete corrected version of {p.name}."
    )
    if extra_instruction:
        prompt += f"\n\nAlso: {extra_instruction}"

    history = []
    result, _ = run_agent(prompt, history, yolo=yolo)

    # Verify the fix worked
    separator()
    info(f"Verifying fix...")
    ok2, output2 = run_and_capture(str(p))
    if ok2:
        success(f"Fixed! {p.name} now runs successfully.")
        if output2.strip():
            print(output2)
    else:
        warning(f"Fix attempt did not fully resolve the error:")
        print(output2)
        info("Try: codey --read " + str(p) + " \"fix this error: " + output2[:100] + "\"")
