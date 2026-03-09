import sys
import logging
from rich.console import Console
from rich.theme import Theme
from typing import Optional

_theme = Theme({
    "info":    "bold cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error":   "bold red",
    "tool":    "bold magenta",
    "think":   "dim italic white",
    "user":    "bold blue",
})

console = Console(theme=_theme, highlight=False)

# Log level mapping
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

# Current log level (can be set from config)
_current_log_level: int = logging.INFO

# File handler for daemon logging
_file_handler: Optional[logging.FileHandler] = None
_file_logger: Optional[logging.Logger] = None


def set_log_level(level: str):
    """Set the current log level."""
    global _current_log_level
    _current_log_level = LOG_LEVELS.get(level.upper(), logging.INFO)


def setup_file_logging(log_file: str):
    """Set up file logging for daemon mode."""
    global _file_handler, _file_logger
    
    _file_logger = logging.getLogger("codey_daemon")
    _file_logger.setLevel(logging.DEBUG)
    
    _file_handler = logging.FileHandler(log_file, mode='a')
    _file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    _file_handler.setFormatter(formatter)
    
    _file_logger.addHandler(_file_handler)


def _log_to_file(level: str, message: str):
    """Log a message to the file handler."""
    if _file_logger:
        log_method = getattr(_file_logger, level.lower(), _file_logger.info)
        log_method(message)


def info(msg):
    if _current_log_level <= logging.INFO:
        console.print(f"[info]ℹ  {msg}[/info]")
    _log_to_file("info", msg)

def success(msg):
    if _current_log_level <= logging.INFO:
        console.print(f"[success]✓  {msg}[/success]")
    _log_to_file("info", msg)

def warning(msg):
    if _current_log_level <= logging.WARNING:
        console.print(f"[warning]⚠  {msg}[/warning]")
    _log_to_file("warning", msg)

def error(msg):
    if _current_log_level <= logging.ERROR:
        console.print(f"[error]✗  {msg}[/error]")
    _log_to_file("error", msg)

def think(msg):
    if _current_log_level <= logging.DEBUG:
        console.print(f"[think]💭 {msg}[/think]")
    _log_to_file("debug", msg)

def debug(msg):
    """Debug level logging."""
    if _current_log_level <= logging.DEBUG:
        console.print(f"[dim]🔍 {msg}[/dim]")
    _log_to_file("debug", msg)

def tool_call(name, args):
    console.print(f"[tool]🔧 TOOL [{name}][/tool]")

def tool_result(result):
    preview = str(result)[:200]
    console.print(f"[success]   ↳ {preview}[/success]")

def separator():
    console.rule(style="dim")

def confirm(question) -> bool:
    """Keep asking until we get a real y or n — never auto-cancel."""
    sys.stdout.flush()
    sys.stderr.flush()
    while True:
        try:
            ans = console.input(f"\n⚠  {question} [y/N]: ").strip().lower()
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no", ""):
                # Only accept empty as No if it was a deliberate Enter
                # Re-prompt if stdin might have leftover newlines
                return False
        except EOFError:
            # stdin closed (e.g. piped input) — default to False
            return False
        except KeyboardInterrupt:
            print()
            return False
