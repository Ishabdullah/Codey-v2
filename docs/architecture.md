# Architecture

## Three-Model Design

Codey-v2 runs three purpose-built models simultaneously, each on its own port:

| Model | Port | Role |
|-------|------|------|
| Qwen2.5-Coder-7B Q4_K_M | 8080 | Primary agent — coding, reasoning, tool use |
| Qwen2.5-0.5B Q8_0 | 8081 | Planner + conversation summarizer |
| nomic-embed-text-v1.5 Q4 | 8082 | Embedding encoder for RAG retrieval |

The 7B model handles all user-facing work. The 0.5B runs independently for task planning and context compression so the 7B never burns tokens managing its own context. The embedding model runs continuously to serve retrieval queries during inference.

---

## System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   CLI Client (codey2)                   │
│  User commands · flags · task queries · /status         │
└─────────────────────────────────────────────────────────┘
                          │  Unix socket
                          ▼
┌─────────────────────────────────────────────────────────┐
│                Daemon Core (codeyd2)                    │
│  asyncio event loop · signal handlers · socket server   │
└─────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   Planner        │ │   Memory         │ │   Tools          │
│  · Task queue    │ │  · Working       │ │  · Filesystem    │
│  · Dependencies  │ │  · Project       │ │  · Shell         │
│  · Recovery      │ │  · Long-term     │ │  · Search        │
│  · Background    │ │  · Episodic      │ │  · Git           │
└──────────────────┘ └──────────────────┘ └──────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                     LLM Layer                           │
│  Port 8080 — Qwen2.5-Coder-7B (primary agent)          │
│  Port 8081 — Qwen2.5-0.5B (planner + summarizer)       │
│  Port 8082 — nomic-embed-text (RAG encoder)             │
│  /v1/chat/completions · ChatML · thermal management     │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                 State Store (SQLite)                    │
│  Persistent memory · task queue · episodic log          │
│  Model state · embeddings · checkpoints                 │
└─────────────────────────────────────────────────────────┘
```

---

## Memory System

Conversation context is managed across four tiers:

```
┌─────────────────────────────────────────┐
│  Working Memory (in-memory, evicted)    │
│  Currently edited files                 │
│  Cleared after each task completes      │
└─────────────────────────────────────────┘
              │
┌─────────────────────────────────────────┐
│  Project Memory (persistent)            │
│  CODEY.md, README.md                    │
│  Never evicted — loaded at daemon start │
└─────────────────────────────────────────┘
              │
┌─────────────────────────────────────────┐
│  Long-term Memory (embeddings)          │
│  768-dim vectors via nomic-embed        │
│  Semantic search via cosine similarity  │
└─────────────────────────────────────────┘
              │
┌─────────────────────────────────────────┐
│  Episodic Memory (action log)           │
│  Append-only log of all actions         │
│  SQLite via state store                 │
└─────────────────────────────────────────┘
```

### Context Compression

When in-context token usage hits 55% of the context window, Codey compresses history:

1. The 4 most recent messages are always kept intact.
2. Pinned messages (file writes, errors, existing summaries) are never dropped.
3. Oldest unpinned turns are dropped until usage falls to 40%.
4. The 0.5B model generates a ≤100-word "Previously:" summary of what was dropped.
5. An existing `[CONVERSATION SUMMARY]` is never re-summarized — it stays pinned.

This keeps the 7B model focused on current work without losing critical context.

---

## What Persists Between Sessions

This table covers exactly what Codey saves, where it lives, and how long it lasts — so you know what context the model actually has when you start a new session.

| What | Where | Survives restart? | Expires? | How to clear |
|------|-------|------------------|----------|--------------|
| Last 6 turns of conversation | `~/.codey_sessions/<project-hash>.json` | Yes | After 2 hours of inactivity | `/clear` in-chat or `codey2 --clear-session` |
| Project memory (`CODEY.md`) | `<project>/CODEY.md` | Yes | Never | Edit or delete the file manually |
| Action log (every tool call) | `~/.codey-v2/state.db` | Yes | Never (append-only) | Delete `~/.codey-v2/state.db` |
| Open files / working context | In-memory only | No | On exit | — |
| File undo history | In-memory only | No | On exit | — |
| Knowledge base embeddings | `~/.codey-v2/kb/` (if set up) | Yes | Never | `codey2 kb clear` |

### What Codey does NOT do

- **Does not learn from your conversations.** The RAG index only contains what you explicitly load with `/load`, `/read`, or the knowledge base pipeline — not anything you've said or typed.
- **Does not send data anywhere.** All state is local. The only exception is peer CLI escalation (Claude Code, Gemini CLI, Qwen CLI), which requires explicit confirmation before any files are shared.
- **Does not auto-recover deep context on large projects.** The session window is 6 turns (expires in 2 hours). For long-running projects, `CODEY.md` is the primary source of persistent context — if it is sparse or missing, Codey starts each session with limited knowledge of your project.

### Practical advice for larger projects

1. Run `/init` at the start of a project to generate `CODEY.md`. Keep it updated as the project grows — it is the single most important thing for cross-session accuracy.
2. Use `--no-resume` if you want to start a session completely fresh without the last 6 turns being loaded.
3. The action log (`state.db`) grows indefinitely. It is not used for inference — only for observability (`/history`). Safe to delete if it grows large.

---

## Project Structure

```
~/codey-v2/
├── codey2                   # CLI client
├── codeyd2                  # Daemon manager
├── main.py                  # Entry point
├── core/
│   ├── daemon.py            # Daemon core and Unix socket server
│   ├── daemon_config.py     # Configuration manager
│   ├── state.py             # SQLite state store
│   ├── task_executor.py     # Task execution with tool loop and recovery
│   ├── planner_v2.py        # Internal task planner
│   ├── plannd.py            # 0.5B planner daemon and get_plan_from_7b
│   ├── planner_client.py    # Async interface to the planner
│   ├── summarizer.py        # Context compression (sliding window + 0.5B)
│   ├── background.py        # Background tasks and file watches
│   ├── filesystem.py        # Direct filesystem access
│   ├── memory_v2.py         # Four-tier memory system
│   ├── embeddings.py        # Embedding model integration
│   ├── inference_v2.py      # Chat completions inference
│   ├── inference_hybrid.py  # Chat completions HTTP backend
│   ├── context.py           # Context block assembly
│   ├── checkpoint.py        # Self-modification safety
│   ├── observability.py     # Self-state queries
│   ├── recovery.py          # Error recovery strategies
│   ├── thermal.py           # Thermal and battery management
│   ├── tokens.py            # Token estimation and usage bar
│   ├── peer_cli.py          # Peer CLI escalation manager
│   ├── peer_shell.py        # PTY/subprocess runners for peer CLIs
│   ├── learning.py          # Learning system coordinator
│   ├── preferences.py       # User preference learning
│   ├── voice.py             # TTS + STT via Termux:API
│   ├── linter.py            # Static analysis: ruff / flake8 / mypy / ast
│   └── githelper.py         # Git: branches, merge, conflict detection
├── tools/
│   ├── file_tools.py        # File operations
│   ├── patch_tools.py       # Patch / diff tools
│   ├── shell_tools.py       # Shell execution
│   ├── kb_scraper.py        # Knowledge base indexer
│   └── kb_semantic.py       # Semantic index builder
├── utils/
│   ├── config.py            # All configuration constants
│   └── logger.py            # Structured logging
├── prompts/
│   └── system_prompt.py     # Agent system prompt
└── docs/                    # This documentation
```

---

## Python API

### Daemon

```python
from core.daemon import daemon_status, daemon_health, daemon_ping

status = daemon_status()   # dict with uptime, pid, model state
health = daemon_health()   # CPU, memory, task queue
pong   = daemon_ping()     # True if daemon is alive
```

### State Store

```python
from core.state import get_state_store

state = get_state_store()

state.set("key", "value")
value = state.get("key")
state.delete("key")

task_id = state.add_task("description")
state.start_task(task_id)
state.complete_task(task_id, "result")
state.fail_task(task_id, "error")

state.log_action("action", "details")
actions = state.get_recent_actions(limit=50)
```

### Memory

```python
from core.memory_v2 import get_memory

memory = get_memory()

memory.add_to_working("file.py", content, tokens)
memory.clear_working()

memory.add_to_project("CODEY.md", content, is_protected=True)

memory.store_in_longterm("file.py", content)
results = memory.search("authentication code", limit=5)

memory.log_action("file_modified", "auth.py")
```

### Planner

```python
from core.planner_v2 import get_planner

planner = get_planner()

task_id  = planner.add_task("Build a REST API")
task_ids = planner.add_tasks(["Set up project", "Create app", "Write tests"])
task     = planner.get_next_task()
subtasks = planner.breakdown_complex_task("Build a Flask app")
alt      = planner.adapt(task_id, "Permission denied")
```
