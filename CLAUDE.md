# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running Codey-v2

```bash
# Interactive REPL
python main.py

# One-shot task
python main.py "create a Flask hello world"

# Skip all confirmations
python main.py --yolo "task"

# Disable orchestrator (for simple tasks that shouldn't be planned)
python main.py --no-plan "task"

# Pre-load files into context before the task
python main.py --read core/agent.py "refactor the tool loop"

# Override model settings at runtime
python main.py --threads 6 --ctx 8192
```

The `codey-v2` shell script in the repo root is just a launcher: `python ~/codey-v2/main.py "$@"`.

No tests exist yet — `tests/` is planned but not implemented (see `todo.md`).

## Architecture

### Request flow

```
main.py (REPL) → run_agent() → build_system_prompt() → infer() → parse_tool_call()
                                                                      ↓ tool found
                                                               execute_tool() → loop
                                                                      ↓ no tool
                                                               return response
```

**`core/agent.py`** is the central file. `run_agent()` contains:
- Q&A vs tool detection (`is_qa`) — messages matching question patterns skip tools entirely
- Complex task detection delegates to `core/orchestrator.py` (`is_complex`) which may split the request into a subtask queue before entering the tool loop
- The ReAct loop: infer → parse → execute → infer again (max 6 steps)
- Hallucination guard (`is_hallucination`) — catches cases where the model claims to have done something without using a tool
- Duplicate tool call detection to prevent infinite loops

### Inference backend

`core/inference.py` starts a `llama-server` subprocess (llama.cpp) on port 8081 and communicates via HTTP `/v1/chat/completions`. The server is started lazily on the first call and stays running for the session. `stream=True` is used in the agent loop so tokens print live. Stop sequences are configured here — including section headers like `\n## Project Map` to prevent the model from echoing system prompt content.

### Tool call protocol

The model outputs tool calls as:
```
<tool>
{"name": "write_file", "args": {"path": "foo.py", "content": "..."}}
</tool>
```
`parse_tool_call()` in `agent.py` handles malformed JSON with multiple fallback strategies. All 7 tools (`write_file`, `patch_file`, `read_file`, `append_file`, `list_dir`, `shell`, `search_files`) are dispatched through the `TOOLS` dict.

### Memory system

`core/memory.py` — `MemoryManager` singleton (`memory`). Files are stored with LRU metadata and relevance-scored against the current message to fit within the 800-token file budget. `core/context.py` is a thin wrapper over it.

The system prompt is built fresh each call in `build_system_prompt()` in `agent.py`:
1. Base `SYSTEM_PROMPT` from `prompts/system_prompt.py`
2. `CODEY.md` contents (if found in project root) or project summary
3. Repo map (capped at ~1200 chars) from `core/project.py`
4. Relevant loaded files from `MemoryManager`

### Configuration

All tunable knobs are in `utils/config.py`:
- `MODEL_CONFIG` — `n_ctx`, `n_threads`, `temperature`, `max_tokens`, `kv_type`, `stop` tokens
- `AGENT_CONFIG` — `max_steps`, `history_turns`, `confirm_shell`, `confirm_write`
- `WORKSPACE_ROOT` — set to `cwd` at import time; file ops outside this path require confirmation

### Safety boundaries

- **Protected files** — `tools/file_tools.py::PROTECTED_FILES` lists Codey-v2's own source files. The agent cannot overwrite them.
- **Workspace restriction** — reads/writes outside `WORKSPACE_ROOT` trigger a confirmation prompt.
- **Shell confirmation** — dangerous commands (`rm`, `chmod`, `curl`, etc.) always confirm; all shell commands confirm unless `--yolo`.
- **Secret redaction** — `core/sessions.py` strips API keys, GitHub tokens, and passwords before saving session history to `~/.codey_sessions/`.

## Key Patterns When Modifying Codey-v2

**Adding a new tool**: Register it in `TOOLS` dict and `ROGUE_TAG_MAP` in `agent.py`, add to `SYSTEM_PROMPT` in `prompts/system_prompt.py`, and implement the handler in `tools/`.

**Changing Q&A vs tool behavior**: The `is_qa` block in `run_agent()` (around line 311) and `is_complex()` in `orchestrator.py` share the same action keyword logic. Keep them in sync.

**Adjusting context budget**: Token budgets are constants at the top of `core/memory.py`. The total must not exceed `MODEL_CONFIG["n_ctx"]`.

**`patch_file` requires exact string match**: `old_str` must appear exactly once in the file. The model must read the file first with `read_file` before attempting a patch. Auto-loading from prompt (`auto_load_from_prompt`) handles files mentioned by name in the user message.
