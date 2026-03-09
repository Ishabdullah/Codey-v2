# Codey-v2 — Full Code Audit & Review

**Date:** 2026-03-07
**Audited by:** Code audit of all source files in `/codey-v2/`
**Scope:** All `.py` files in `main.py`, `core/`, `tools/`, `utils/`, `prompts/`; shell scripts and config files. No documentation files consulted.
**Status:** All 34 findings fixed.

---

## Table of Contents

1. [Architecture & Code Flow Summary](#architecture--code-flow-summary)
2. [Critical Bugs — Runtime Errors](#critical-bugs--runtime-errors)
3. [Security Issues](#security-issues)
4. [Design & Architectural Issues](#design--architectural-issues)
5. [Code Quality Issues](#code-quality-issues)
6. [Performance Issues](#performance-issues)
7. [Incomplete Implementations](#incomplete-implementations)
8. [Positive Observations](#positive-observations)
9. [Findings Summary Table](#findings-summary-table)

---

## Architecture & Code Flow Summary

The entry point is `main.py`, which parses CLI args, applies config overrides, and calls `repl()`. The REPL calls `run_agent()` in `core/agent.py` for every user message.

```
main.py::main()
  → parse_args(), apply_overrides()
  → repl() → load_model() [validates binary/model paths]
             → run_agent(message, history, ...)
               → is_complex()       [orchestrator.py]
               → plan_tasks()       [orchestrator.py, if complex]
               → build_system_prompt() → SYSTEM_PROMPT + CODEY.md + repo_map + file_ctx
               → infer(messages)    [inference.py → HTTP → llama-server]
               → parse_tool_call()  [extract JSON from <tool>…</tool>]
               → execute_tool()     [dispatches to tools/]
               → loop until no tool call or max_steps
```

**Tools dispatch map (`TOOLS` dict in `agent.py`):**
- `write_file` → `tools/file_tools.py::tool_write_file` → `core/filesystem.py::Filesystem.write`
- `patch_file` → `tools/patch_tools.py::tool_patch_file` (has its own confirmation + snapshot)
- `read_file` → `tools/file_tools.py::tool_read_file` → `Filesystem.read`
- `append_file` → `tools/file_tools.py::tool_append_file` → `Filesystem.append`
- `list_dir` → `tools/file_tools.py::tool_list_dir` → `Filesystem.list_dir`
- `shell` → `tools/shell_tools.py::shell` (has confirmation + dangerous-cmd check)
- `search_files` → `tools/shell_tools.py::search_files` (subprocess list args, injection-safe)

**Memory layers:**
- `core/memory.py::MemoryManager` — LRU+scored file context
- `core/context.py` — thin wrapper over MemoryManager (no duplicate `_loaded_files` dict)
- `core/summarizer.py` — compresses history when `> 1500 tokens`
- `core/sessions.py` — saves/loads `~/.codey_sessions/*.json`

---

## Critical Bugs — Runtime Errors

### BUG-1: `_codeymd_cache` undefined in `core/codeymd.py` — CODEY.md permanently broken ✅ FIXED

**File:** `core/codeymd.py:22`
**Severity:** Critical

`_codeymd_cache` is referenced but never declared in the module. The variable is used in `read_codeymd()` to prevent repeated log messages, but it was never initialized.

**Impact:** The `except Exception: return ""` silently swallows the NameError. Since the NameError fires before `return content`, the function always returns `""` when a CODEY.md file exists. This causes `build_system_prompt()` to always fall back to the generic project summary, completely disabling the CODEY.md project memory system — a core advertised feature.

**Fix applied:** Added `_codeymd_cache: dict = {}` at module level in `core/codeymd.py` after `CODEYMD_FILENAME = "CODEY.md"`.

---

### BUG-2: `Path` not imported in `tools/shell_tools.py` ✅ FIXED

**File:** `tools/shell_tools.py:16`
**Severity:** Critical

The `is_dangerous()` function uses `Path` which is never imported in the module. Every call to `shell()` calls `is_dangerous()` first, making ALL shell command executions raise `NameError`.

**Fix applied:** Added `from pathlib import Path` to imports in `shell_tools.py`.

---

### BUG-3: `planner_v2.py::fail_task` — parameter shadows imported logger function ✅ FIXED

**File:** `core/planner_v2.py:226`
**Severity:** High

The `fail_task` and `adapt` methods accepted a parameter named `error`, which shadowed the `error` logging function imported at module level. Calling `error(...)` inside the method raised `TypeError: 'str' object is not callable`.

**Fix applied:** Renamed the parameter to `error_msg` throughout both `fail_task()` and `adapt()`.

---

### BUG-4: `Daemon` started from `main.py` without PID file check ✅ FIXED

**File:** `main.py:459`, `core/daemon.py:511`
**Severity:** High

When the daemon was launched from `main.py --daemon`, the `check_pid_file()` call that exists in the standalone `daemon.main()` was skipped, allowing multiple daemon instances.

**Fix applied:** Added `check_pid_file()` call before `Daemon()` instantiation in `main.py`:
```python
from core.daemon import Daemon, check_pid_file
if check_pid_file():
    error("Daemon is already running. Use --daemon-stop to shut it down.")
    sys.exit(1)
```

---

### BUG-5: `Filesystem.read` — `ValueError` when logging path for CODE_DIR files ✅ FIXED

**File:** `core/filesystem.py:112`
**Severity:** Medium

`path.relative_to(self.workspace)` raised `ValueError` when reading files outside the workspace (e.g., Codey's own source files in CODE_DIR). The `ValueError` was re-wrapped as `FilesystemAccessError`.

**Fix applied:** All 5 `relative_to(self.workspace)` log sites in `filesystem.py` now use a try/except fallback that shows the full path when relative path computation fails.

---

### BUG-6: `check_pid_file` does not handle `PermissionError` ✅ FIXED

**File:** `core/daemon.py:64`
**Severity:** Medium

`os.kill(pid, 0)` can raise `PermissionError` if the process exists but is owned by a different user. This was not caught.

**Fix applied:** Added `except PermissionError: return True` to `check_pid_file()`.

---

## Security Issues

### SEC-1: Command Injection in `search_files` tool ✅ FIXED

**File:** `tools/shell_tools.py:61`
**Severity:** Critical

The `search_files` tool built a shell command by directly interpolating LLM-generated `pattern` and `path` strings without sanitization, then executed it with `yolo=True`.

**Fix applied:** Rewrote `search_files` to use `subprocess.run` with a list of arguments:
```python
def search_files(pattern: str, path: str = ".") -> str:
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
```
No shell interpolation; `yolo=True` removed.

---

### SEC-2: Daemon mode auto-confirms all shell commands without restriction ✅ FIXED

**File:** `core/task_executor.py:329`
**Severity:** High

Daemon `_confirm_shell()` previously called `shell(command)` for all commands with no restrictions.

**Fix applied:** Added an explicit allowlist of safe command prefixes in `_confirm_shell()`. Commands not matching the allowlist return `[BLOCKED]` with an explanation message:
```python
DAEMON_ALLOWED_PREFIXES = (
    "python", "python3", "pip", "pip3",
    "pytest", "ls", "cat", "echo", "grep", "find",
    "git status", "git log", "git diff", "git show",
    "cd ", "pwd", "which", "env", "printenv",
)
```

---

### SEC-3: Session file uses MD5 for path hashing ✅ FIXED

**File:** `core/sessions.py:46`
**Severity:** Low

Changed `hashlib.md5` to `hashlib.sha256` for session filename hashing.

---

### SEC-4: `write_file` tool skips undo snapshots ✅ FIXED

**File:** `core/filesystem.py:120`
**Severity:** Medium

`Filesystem.write()` did not call `snapshot()` before overwriting files, making `/undo` ineffective for `write_file` operations.

**Fix applied:** Added `from core.filehistory import snapshot as _snapshot` import and call `_snapshot(str(path))` before `path.write_text(...)` when the file already exists.

---

### SEC-5: Secret redaction pattern has a logic flaw ✅ FIXED

**File:** `core/sessions.py:30`
**Severity:** Low

The convoluted group-count detection logic was replaced with a clean tuple-based pattern list:
```python
_SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{48}"),                    "[REDACTED]"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"),                   "[REDACTED]"),
    (re.compile(r'("password"\s*:\s*)"[^"]+"'),             r'\1"[REDACTED]"'),
    (re.compile(r'(password\s*=\s*)\S+'),                   r'\1[REDACTED]'),
    (re.compile(r'(api[_-]key\s*[:=]\s*)[a-zA-Z0-9_\-]{20,}', re.I), r'\1[REDACTED]'),
]
```

---

## Design & Architectural Issues

### ARCH-1: Two competing summarization systems ✅ FIXED

**Files:** `core/summarizer.py`, `core/memory.py:127`
**Severity:** Medium

Both `summarize_history` and `compress_summary` could fire in the same `run_agent()` call, triggering two LLM inference calls for compression.

**Fix applied:** Changed to `elif` so only one summarization path runs per call:
```python
if len(history) >= 8:
    history = _mem.compress_summary(history)
elif should_summarize(history):
    history = summarize_history(history)
```

---

### ARCH-2: `WORKSPACE_ROOT` captured at import time, not updated on `/cwd` ✅ FIXED

**File:** `utils/config.py:66`
**Severity:** Medium

After `/cwd` changed the working directory, `WORKSPACE_ROOT` remained stale, causing `Filesystem` to reject files in the new working directory.

**Fix applied:** The `/cwd` handler in `main.py` now updates `utils.config.WORKSPACE_ROOT`, calls `reset_filesystem()` to rebuild the singleton, calls `invalidate_cache()` for the project cache, and clears `_ignore_cache` from context.py.

---

### ARCH-3: `_loaded_files` in `context.py` diverges from `_mem._files` ✅ FIXED

**File:** `core/context.py:12`
**Severity:** Low

Removed the redundant `_loaded_files` dict entirely from `context.py`. The `_mem` singleton is now the sole source of truth for all loaded file state.

---

### ARCH-4: Module-level side effects in `core/daemon.py` ✅ FIXED

**File:** `core/daemon.py:34`
**Severity:** Medium

All initialization (logging setup, mkdir, config loading) moved from module level into `Daemon.__init__`. Module-level code now only defines stable path constants with hardcoded defaults:
```python
DAEMON_DIR   = Path.home() / ".codey-v2"
PID_FILE     = DAEMON_DIR / "codey-v2.pid"
SOCKET_FILE  = DAEMON_DIR / "codey-v2.sock"
LOG_FILE     = DAEMON_DIR / "codey-v2.log"
```

---

### ARCH-5: Two different `is_complex` implementations ✅ FIXED

**Files:** `core/orchestrator.py`, `core/planner.py`
**Severity:** Low

Removed the local `is_complex` function and `COMPLEX_TASK_SIGNALS` list from `core/planner.py`. Now imports the single canonical implementation:
```python
from core.orchestrator import is_complex
```

---

### ARCH-6: Token count uses words/second, displayed as tokens/second ✅ FIXED

**File:** `core/inference.py:135`
**Severity:** Low

Changed TPS calculation in the streaming path from `len(response_text.split()) / _elapsed` (word count) to `(len(response_text) / 4) / _elapsed` (char/4 token approximation), consistent with the rest of the codebase.

---

### ARCH-7: Thermal management cannot affect a running llama-server ✅ FIXED

**File:** `core/thermal.py:86`
**Severity:** Medium

Thermal manager now sets `self.restart_recommended = True` when it reduces threads. `_start_server()` in `inference.py` checks this flag and restarts the server with the updated thread count on the next inference call:
```python
if tm.restart_recommended:
    info(f"Thermal: restarting server with {tm.current_threads} threads...")
    _server_proc.terminate()
    _server_proc.wait(timeout=10)
    _server_proc = None
    tm.restart_recommended = False
```

---

## Code Quality Issues

### QUAL-1: `extract_json` lambda loop uses misleading `__name__` check ✅ FIXED

**File:** `core/agent.py:102`
**Severity:** Low

Replaced the confusing lambda loop with explicit sequential tries:
```python
for s in [candidate, cleaned]:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        pass
```

---

### QUAL-2: `loader.py` hardcodes llama-server path, ignoring `config.py` ✅ FIXED

**File:** `core/loader.py:6`
**Severity:** Medium

Removed the hardcoded `LLAMA_SERVER` constant. `load_model()` now uses `LLAMA_SERVER_BIN` imported from `utils.config`, matching the path used by `inference.py`.

---

### QUAL-3: `import os` inside function body in `main.py` ✅ FIXED

**File:** `main.py:166`
**Severity:** Low

Removed the redundant `import os` inside the `/search` command handler. `os` is already imported at module level (line 3).

---

### QUAL-4: `--no-resume` flag documented in `/help` but not implemented ✅ FIXED

**File:** `main.py:368`
**Severity:** Low

Added `--no-resume` to `parse_args()` and wired it to `repl()`:
- `parse_args()` now defines `--no-resume` as `action="store_true"`
- `repl()` accepts `no_resume=False` parameter
- When `no_resume=True`, session loading is skipped entirely
- Default behavior is now auto-resume from cwd-based session file on every startup

---

### QUAL-5: Duplicate `import time` inside `infer()` ✅ FIXED

**File:** `core/inference.py:111`
**Severity:** Trivial

Removed the `import time as _time` inside `infer()`. All time calls now use the module-level `import time`.

---

### QUAL-6: `is_error` in `agent.py` only works for the `shell` tool ✅ FIXED

**File:** `core/agent.py:175`
**Severity:** Low

Extended `is_error()` to detect errors from all tools:
```python
def is_error(result, tool_name):
    if not isinstance(result, str):
        return False
    result_lower = result.lower()
    if "[cancelled]" in result_lower:
        return False
    # All tools: treat [ERROR] prefix as an error
    if result.startswith("[ERROR]"):
        return True
    # Shell-specific: detect Python tracebacks and command failures
    if tool_name == "shell":
        error_signals = [...]
        return any(s in result_lower for s in error_signals)
    return False
```

---

### QUAL-7: `summarizer.py` defines its own `estimate_tokens` duplicating `tokens.py` ✅ FIXED

**File:** `core/summarizer.py:25`
**Severity:** Low

Removed the local `estimate_tokens` function from `summarizer.py`. Now imports and uses `estimate_messages_tokens` from `core.tokens`:
```python
from core.tokens import estimate_messages_tokens
...
def should_summarize(history):
    return estimate_messages_tokens(history) > SUMMARY_THRESHOLD
```

---

### QUAL-8: `context.py::is_ignored` re-reads `.codeyignore` on every call ✅ FIXED

**File:** `core/context.py:25`
**Severity:** Performance

Added a module-level `_ignore_cache` dict keyed by `(cwd_str, mtime)`. The cache is populated on first call and reused until the file's mtime changes or the cwd changes. Cache is cleared in the `/cwd` handler in `main.py`.

---

## Performance Issues

### PERF-1: SQLite connection created and closed per operation ✅ FIXED

**File:** `core/state.py`
**Severity:** Medium

Rewrote `StateStore` to use a persistent connection opened in `__init__` with `check_same_thread=False`. WAL journal mode enabled for better concurrent reads. Removed all per-method `_get_connection()` / `conn.close()` calls. Added a `close()` method and updated `reset_state_store()` to call it.

---

### PERF-2: `get_repo_map` scans up to 50 files on every `build_system_prompt` call ✅ FIXED

**File:** `core/project.py:32`
**Severity:** Medium

Added `_repo_map_cache` and `_repo_map_cwd` module-level variables. `get_repo_map()` returns the cached result immediately when called for the same cwd. `invalidate_cache()` now also resets `_repo_map_cache` and `_repo_map_cwd`.

---

### PERF-3: History can grow unbounded within a session ✅ FIXED

**File:** `core/agent.py:340`
**Severity:** Medium

After `compress_summary()`, the history list is now trimmed to `history_turns * 2` entries:
```python
if len(history) >= 8:
    history = _mem.compress_summary(history)
    keep = AGENT_CONFIG["history_turns"] * 2
    if len(history) > keep:
        history = history[-keep:]
```

---

## Incomplete Implementations

### INCOMPLETE-1: `Daemon._process_planner_tasks` is a stub ✅ FIXED

**File:** `core/daemon.py:396`
**Severity:** High

Replaced the stub (immediate fake completion) with a real dispatch that uses `TaskExecutor._execute_task()`:
- Skips if executor is already busy (`executor.current_task` is set)
- Calls `planner.start_task()` to update in-memory and SQLite state
- Awaits `executor._execute_task(description)` with the configured timeout
- Calls `planner.complete_task()` on success or `planner.fail_task()` on error/timeout

---

### INCOMPLETE-2: `BackgroundTaskManager.stop_task` does not actually stop tasks ✅ FIXED

**File:** `core/background.py:167`
**Severity:** Medium

Added `_asyncio_task: Optional[asyncio.Task]` field to `BackgroundTask`. The `asyncio.Task` handle is stored when `start_task()` creates it via `asyncio.create_task()`. `stop_task()` now calls `.cancel()` on the stored handle:
```python
if task._asyncio_task and not task._asyncio_task.done():
    task._asyncio_task.cancel()
```
The `_run_task` coroutine already catches `CancelledError` and sets status to `STOPPED`.

---

### INCOMPLETE-3: `planner_v2` dependency tracking is not persisted ✅ FIXED

**File:** `core/planner_v2.py:150`, `core/state.py`
**Severity:** Medium

Two changes:
1. Added `dependencies TEXT DEFAULT '[]'` and `retry_count INTEGER DEFAULT 0` columns to the `task_queue` table in `state.py`. Existing DBs are migrated via `ALTER TABLE ... ADD COLUMN` with `try/except OperationalError`.
2. Implemented `_update_task_dependencies()` in `planner_v2.py` to persist JSON-encoded dependency list to SQLite. `fail_task()` also calls `state.increment_retry()` to keep the DB in sync, and resets status to `'pending'` in SQLite for retry attempts.

---

### INCOMPLETE-4: Socket shutdown command doesn't stop daemon ✅ FIXED

**File:** `core/daemon.py:233`
**Severity:** Medium

Added `shutdown_callback` parameter to `DaemonServer.__init__`. Added `_trigger_shutdown()` method to `Daemon` that sets `self.running = False` and closes the server. `DaemonServer` is now constructed with `shutdown_callback=self._trigger_shutdown`. `_handle_shutdown` calls the callback instead of setting `self.running = False` (the wrong object).

---

### INCOMPLETE-5: `StrategySwitcher` fallback strategies are advisory only ✅ FIXED

**File:** `core/recovery.py`, `core/task_executor.py`
**Severity:** Medium

Added `execute_strategy(strategy, context)` to `recovery.py` that actually performs the recovery action:
- `pip_install` → extracts package name from `ImportError` and runs `pip install <pkg>`
- `search_files` / `create_then_modify` → runs `find` to locate similar files
- `mkdir_then_write` → creates parent directory with `mkdir -p`
- `verify_dependencies` → runs `which <cmd>` to check tool availability
- `search_error_message` → returns trimmed error text for model context
- `run_single_test` → extracts failing test ID and runs `pytest <test_id> -v --tb=short`
- Default → returns advisory description

Updated `task_executor.py` to call `execute_strategy()` and record success/failure based on actual result, then include the real recovery output in the model context message.

---

## Positive Observations

- **Robust JSON extraction** (`extract_json` in `agent.py`) handles malformed LLM output gracefully through multiple fallback strategies including regex extraction.
- **Hallucination guard** (`is_hallucination`) prevents the model from claiming to have created files without actually calling `write_file`.
- **Duplicate tool call detection** prevents infinite loops where the model repeatedly calls the same tool.
- **Rich display system** (`core/display.py`) provides clear syntax-highlighted panels for file writes, diffs, and shell output.
- **`patch_file` uniqueness enforcement** in `patch_tools.py` rejects ambiguous patches (match count != 1), preventing unintended multi-site edits.
- **Secret redaction** in `sessions.py` scrubs API keys and tokens from persisted session history.
- **LRU file eviction** in `MemoryManager` keeps the context window lean without manual intervention.
- **`is_ignored` patterns** respect `.codeyignore` for customizable exclusions.
- **Graceful interrupt handling** in `orchestrator.py::run_queue` saves queue state on SIGINT for resumption.
- **Thread-safe SQLite** via `threading.Lock` in `StateStore`.
- **`--yolo` mode** with explicit CLI flag rather than a hidden/global setting.

---

## Findings Summary Table

| ID | Severity | File | Description | Status |
|----|----------|------|-------------|--------|
| BUG-1 | **Critical** | `core/codeymd.py:22` | `_codeymd_cache` undefined — CODEY.md feature broken | ✅ Fixed |
| BUG-2 | **Critical** | `tools/shell_tools.py:16` | `Path` not imported — shell tool crashes | ✅ Fixed |
| BUG-3 | **High** | `core/planner_v2.py:226` | `error` param shadows logger function — TypeError | ✅ Fixed |
| BUG-4 | **High** | `main.py:459` | No PID check on `--daemon` — multiple daemon instances | ✅ Fixed |
| BUG-5 | **Medium** | `core/filesystem.py:112` | `relative_to` ValueError for CODE_DIR files | ✅ Fixed |
| BUG-6 | **Medium** | `core/daemon.py:64` | `PermissionError` not caught in PID check | ✅ Fixed |
| SEC-1 | **Critical** | `tools/shell_tools.py:61` | Command injection in `search_files` | ✅ Fixed |
| SEC-2 | **High** | `core/task_executor.py:329` | Daemon auto-confirms all shell commands | ✅ Fixed |
| SEC-3 | **Low** | `core/sessions.py:46` | MD5 used for session filename hashing | ✅ Fixed |
| SEC-4 | **Medium** | `core/filesystem.py:120` | `write_file` skips undo snapshot | ✅ Fixed |
| SEC-5 | **Low** | `core/sessions.py:30` | Fragile secret redaction logic | ✅ Fixed |
| ARCH-1 | **Medium** | `core/agent.py`, `core/memory.py` | Two competing summarization systems | ✅ Fixed |
| ARCH-2 | **Medium** | `utils/config.py:66` | `WORKSPACE_ROOT` stale after `/cwd` change | ✅ Fixed |
| ARCH-3 | **Low** | `core/context.py:12` | `_loaded_files` diverges from `_mem._files` | ✅ Fixed |
| ARCH-4 | **Medium** | `core/daemon.py:34` | Module-level side effects on import | ✅ Fixed |
| ARCH-5 | **Low** | `core/orchestrator.py`, `core/planner.py` | Two different `is_complex` implementations | ✅ Fixed |
| ARCH-6 | **Low** | `core/inference.py:135` | TPS display uses word count, not token count | ✅ Fixed |
| ARCH-7 | **Medium** | `core/thermal.py:86` | Thread reduction has no effect on running server | ✅ Fixed |
| QUAL-1 | **Low** | `core/agent.py:102` | Lambda `__name__` check always True — confusing | ✅ Fixed |
| QUAL-2 | **Medium** | `core/loader.py:6` | `load_model` uses hardcoded path, not `config.py` | ✅ Fixed |
| QUAL-3 | **Low** | `main.py:166` | Redundant `import os` inside function | ✅ Fixed |
| QUAL-4 | **Low** | `main.py:368` | `--no-resume` documented but not implemented | ✅ Fixed |
| QUAL-5 | **Trivial** | `core/inference.py:111` | Duplicate `import time` inside `infer()` | ✅ Fixed |
| QUAL-6 | **Low** | `core/agent.py:175` | `is_error` only works for shell, misleadingly named | ✅ Fixed |
| QUAL-7 | **Low** | `core/summarizer.py:25` | Duplicate `estimate_tokens` diverges from `tokens.py` | ✅ Fixed |
| QUAL-8 | **Medium** | `core/context.py:25` | `.codeyignore` re-read from disk on every call | ✅ Fixed |
| PERF-1 | **Medium** | `core/state.py` | SQLite connection opened/closed per operation | ✅ Fixed |
| PERF-2 | **Medium** | `core/project.py:32` | `get_repo_map` uncached, rescans on every agent step | ✅ Fixed |
| PERF-3 | **Medium** | `core/agent.py:340` | History list grows unbounded in session | ✅ Fixed |
| INCOMPLETE-1 | **High** | `core/daemon.py:396` | Planner task execution is a no-op stub | ✅ Fixed |
| INCOMPLETE-2 | **Medium** | `core/background.py:167` | `stop_task` marks status but doesn't cancel | ✅ Fixed |
| INCOMPLETE-3 | **Medium** | `core/planner_v2.py:150` | Task dependencies not persisted to SQLite | ✅ Fixed |
| INCOMPLETE-4 | **Medium** | `core/daemon.py:233` | Socket shutdown command doesn't stop daemon | ✅ Fixed |
| INCOMPLETE-5 | **Medium** | `core/recovery.py`, `task_executor.py` | Recovery strategies are advisory only, not executed | ✅ Fixed |

---

*End of audit. 34 findings across 6 categories. All 34 fixed.*
