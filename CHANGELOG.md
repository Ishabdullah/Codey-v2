# Changelog

All notable changes to Codey-v2 are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.6.1] - 2026-03-17

### Added — Phase 1: Knowledge Base + RAG Retrieval

This phase implements the foundation of the Recursive LM Architecture:
a local knowledge base with Retrieval-Augmented Generation (RAG) that
injects relevant documentation into the model's context at inference time.

#### New Files
- `tools/kb_scraper.py` — Document chunk indexer. Splits files into
  overlapping 512-word chunks with stable MD5 IDs. Writes
  `.chunks.json` index files to `knowledge/embeddings/`.
- `tools/kb_semantic.py` — Search module with two backends:
  (1) semantic search via `sentence-transformers` (all-MiniLM-L6-v2,
  384-dim cosine similarity); (2) keyword overlap fallback (always
  available, no dependencies). `build_semantic_index()` pre-computes
  embeddings as `vectors.npy` + `mapping.json`.
- `core/retrieval.py` — RAG integration. `retrieve(user_message)`
  searches the KB and returns a formatted `## Reference Material` block
  ready to inject into the system prompt. `retrieve_for_error()` is
  specialised for error recovery. Budget: 2400 chars (~600 tokens).
- `tools/setup_skills.sh` — One-shot setup script. Clones 4 skill
  repositories into `knowledge/skills/`, indexes all of them, and
  optionally builds the semantic index.

#### Knowledge Base Directory Structure
```
knowledge/
  docs/         # User-supplied docs (add .md/.txt files here)
  apis/         # API reference files
  patterns/     # Code pattern templates
  skills/       # Cloned skill repos (created by setup_skills.sh)
  embeddings/   # Auto-generated chunk index + vector store
```

#### Skill Repositories (cloned by setup_skills.sh)
- `ComposioHQ/awesome-claude-skills` — curated skill prompts
- `obra/superpowers` — multi-tool orchestration patterns
- `anthropics/skil` — official skill definition framework
- `PleasePrompto/notebooklm-skill` — document analysis patterns

### Changed
- `utils/config.py` — Added `RETRIEVAL_CONFIG` with tunable knobs:
  `enabled`, `semantic_search`, `max_chunks`, `budget_chars`,
  `semantic_threshold` (default 0.3), `embedding_model`.
- `core/agent.py` — `build_system_prompt()` now calls `retrieve(message)`
  and injects the result as `## Reference Material` after the repo map.
  Wrapped in `try/except` — retrieval never blocks inference.
- Version bumped: `2.6.0` → `2.6.1`

### Context Budget (updated)
```
System prompt:       ~500 tokens
User preferences:    ~100 tokens
CODEY.md/project:    ~200 tokens
Repository map:      ~300 tokens
Reference material:  ~600 tokens  ← NEW (from knowledge base)
Loaded files:       ~1600 tokens  (unchanged; headroom absorbed the new slot)
Recent history:     ~1000 tokens
Current message:     ~400 tokens
Response budget:    ~2048 tokens
Safety headroom:    ~1444 tokens
```

---

## [2.0.0] - 2026-03-08

### Added - Complete 7-Phase Implementation

#### Phase 1: Persistent Daemon + State Store
- Daemon process with Unix socket communication (`core/daemon.py`)
- SQLite state store for persistence (`core/state.py`)
- Daemon configuration management (`core/daemon_config.py`)
- Task executor for background execution (`core/task_executor.py`)
- CLI client (`codey2`) and daemon manager (`codeyd2`) scripts
- Commands: `codeyd2 start|stop|status|restart|reload|config`
- Commands: `codey2 "prompt"`, `codey2 status`, `codey2 task list`

#### Phase 2: Direct Filesystem Access
- Class-based filesystem access (`core/filesystem.py`)
- Removed JSON tool-call parsing overhead
- Direct `read()`, `write()`, `patch()` methods
- Refactored `tools/file_tools.py` for direct access

#### Phase 3: Dual-Model Hot-Swap
- Model loader v2 with hot-swap support (`core/loader_v2.py`)
- Model router for task-based selection (`core/router.py`)
- Inference v2 with model selection (`core/inference_v2.py`)
- Primary model: Qwen2.5-Coder-7B-Instruct (complex tasks)
- Secondary model: Qwen2.5-1.5B-Instruct (simple queries)
- 30-second cooldown to prevent model thrashing

#### Phase 4: Hierarchical Memory
- Four-tier memory system (`core/memory_v2.py`)
  - Working memory: Currently edited files (evicted after task)
  - Project memory: CODEY.md + key files (never evicted)
  - Long-term memory: Embeddings for semantic search
  - Episodic memory: Action history log
- Embeddings integration with sentence-transformers (`core/embeddings.py`)

#### Phase 5: Internal Planning + Background Execution
- Native task planner (`core/planner_v2.py`)
- Task dependency tracking and breakdown
- Background task manager (`core/background.py`)
- Async execution with asyncio event loop
- File system watches with watchdog (optional)

#### Phase 6: Self-Modification + Observability
- Checkpoint system for self-modification (`core/checkpoint.py`)
- Git integration for version control
- Rollback support to any checkpoint
- Observability system (`core/observability.py`)
- `/status` command for full state display
- Removed `PROTECTED_FILES` restrictions

#### Phase 7: Error Recovery + Thermal Management
- Strategy switching on failures (`core/recovery.py`)
- Error classification and fallback strategies
- Thermal management (`core/thermal.py`)
- Inference duration tracking
- Auto-reduce threads after 10 minutes continuous use

### Changed
- All references updated from "Codey v2" to "Codey-v2"
- Daemon files renamed to `codey-v2.*` (pid, sock, log)
- Complete separation from original `codey` directory
- Fixed interactive mode crash (Termux-safe thinking indicator)
- Fixed response display in REPL
- Enhanced error handling throughout

### Fixed
- Interactive mode no longer crashes Termux
- Response display now works correctly in REPL
- PATH conflicts resolved (removed old `codey` from .bashrc)
- Daemon file isolation (no cross-contamination with original codey)
- Thinking indicator safe for Termux (no threads during I/O)

### Technical Notes
- Uses `llama-server` HTTP API instead of direct `llama-cpp-python` binding (Termux/Android platform limitation)
- File watches require optional `watchdog` package
- All 7 implementation phases are complete

---

## [1.0.0] - 2026-02-27

### Added
- Original Codey implementation
- Session-based CLI tool
- ReAct agent with tool calling
- Basic file operations (read, write, patch, append)
- Shell execution with safety checks
- Git integration (`/git` commands)
- Session save/load functionality
- CODEY.md project memory system
- TDD mode (`--tdd`)
- Fix mode (`--fix`)
- Interactive REPL

### Files
- `main.py` - CLI entrypoint and REPL
- `core/agent.py` - ReAct agent loop
- `core/inference.py` - llama-server HTTP client
- `core/memory.py` - Turn-based file memory
- `core/orchestrator.py` - Task planning
- `tools/file_tools.py` - File operations
- `tools/shell_tools.py` - Shell execution

---

## [0.9.0] - 2026-02-20

### Added
- Initial beta release
- Basic tool calling
- File context management
- Project type detection

---

## Future Considerations (Not Yet Implemented)

The following features are explicitly out of scope for v2.0.0 but may be considered for future versions:

1. **NPU Acceleration** - Blocked on llama.cpp upstream support
2. **Vector Memory UI** - Interactive search interface
3. **Multi-Device Sync** - Encrypted cloud state sync
4. **Plugin System** - Third-party tool integration
5. **Voice Interface** - Speech-to-text input
6. **Multi-Agent Collaboration** - Specialized sub-agents
7. **GUI Dashboard** - Web UI for monitoring

---

## Version Compatibility

| Version | Python | Termux | llama.cpp | Models |
|---------|--------|--------|-----------|--------|
| 2.0.0 | 3.12+ | Latest | Latest stable | Qwen2.5-7B, Qwen2.5-1.5B |
| 1.0.0 | 3.10+ | Latest | Latest stable | Qwen2.5-Coder-7B |

---

## Migration Guide

### From v1.0.0 to v2.0.0

**Breaking Changes:**
- Daemon files renamed: `codey.pid` → `codey-v2.pid`, `codey.sock` → `codey-v2.sock`, `codey.log` → `codey-v2.log`
- `PROTECTED_FILES` removed (self-modification now allowed with checkpointing)
- Session format unchanged (backward compatible)

**Upgrade Steps:**
1. Stop any running daemon: `codeyd stop`
2. Remove old daemon files: `rm ~/.codey/codey.*`
3. Update PATH in `.bashrc` (remove old `codey` path)
4. Install v2.0.0: `git pull` or re-run `./install.sh`
5. Start new daemon: `codeyd2 start`

**New Commands:**
```bash
codeyd2 start|stop|status|restart|reload|config  # Daemon management
codey2 status                                     # Full system status
codey2 task list                                  # List recent tasks
codey2 cancel <id>                                # Cancel a task
```

---

## Contributors

Thanks to all contributors who made Codey-v2 possible!

For a complete list of changes, see the git history:
```bash
git log --oneline
```
