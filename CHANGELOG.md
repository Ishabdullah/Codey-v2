# Changelog

All notable changes to Codey-v2 are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v2.7.2] - 2026-03-29

### Added — design_only Phase + Step Cap Raise + Test Coverage

#### Design-only peer phase (`core/agent.py`)

- **`_is_design_only` detection**: When a peer task contains strong design
  keywords (`design`, `plan`, `spec`, `outline`, `feature list`, `architecture`,
  `blueprint`, `roadmap`, `requirements`) without implementation keywords
  (`implement`, `build`, `code`, `develop`, `program`), the peer is sent
  `_DESIGN_INSTRUCTIONS` (prose/markdown, no code blocks) instead of
  `_FORMAT_INSTRUCTIONS` (code block extraction format).

- **`_DESIGN_INSTRUCTIONS`**: New instruction block for design tasks. Explicitly
  instructs the peer: "Do NOT write any code. Do NOT include code blocks.
  Describe features, CLI commands, data model, behavior in plain text/markdown."
  Prevents design specs from including JSON/code examples that `_auto_apply_peer_code`
  would extract and write as source files — the core bug in the Gemini→Qwen pipeline.

- **Design output saved to `{peer_name}_design.md`**: For design tasks, raw peer
  output is written directly to disk (e.g. `gemini_design.md`) and the function
  returns immediately. `_auto_apply_peer_code` is skipped entirely.

- **Disk fallback in `_extract_peer_output_from_history()`**: If a prior peer's
  output is not found in conversation history (e.g. session resumed after context
  compression), automatically reads `{peer_name}_design.md` from cwd. This makes
  the Gemini→Qwen multi-peer pipeline work across context boundaries.

- **Multi-peer injection gated on `not _is_design_only`**: Design steps (step 1
  of a pipeline) are never implementation steps — the injection check is skipped
  to avoid scanning history unnecessarily.

#### Step cap raised 5→8 (`core/plannd.py`, `core/orchestrator.py`, `utils/config.py`)

- **`PLANNER_PROMPT`** (`plannd.py`): "2 to 5 steps" → "2 to 8 steps"
- **`PLAN_PROMPT`** (`orchestrator.py`): "2-5 numbered steps. Max 5 steps." → "2-8 numbered steps. Max 8 steps."
- **`parse_task_list` and `_postprocess_plan`** (`orchestrator.py`): `[:5]` → `[:8]`
- **`PLANNER_MAX_TOKENS`** (`utils/config.py`): `768` → `1024` — gives local 0.5B
  enough room for 8 detailed steps without truncation
- **`CODEY_VERSION`**: `"2.7.0"` → `"2.7.2"`

#### New unit tests

- **`tests/test_parse_tool_call.py`** (22 tests): `parse_tool_call` — JSON in
  `<tool>` tags, rogue tags, block-style `write_file`, malformed JSON (trailing
  comma, incomplete JSON), no-tool case.
- **`tests/test_breadth.py`** (16 tests): `classify_breadth_need` — minimal
  (Q&A), standard (single-file tasks), deep (multi-file/API), edge cases.
- **`tests/test_orchestration.py`** — added `TestPostprocessPlan` (8 tests):
  deduplication of same-file steps, `Run:` step preservation, 8-step cap,
  `Verify` step pass-through. Added `TestIntegrationAgentUtils` (4 tests):
  `extract_json` roundtrip, `parse_tool_call` roundtrip, hallucination
  detection with and without tool use.

### Changed

- `utils/config.py` — `CODEY_VERSION`: `"2.7.0"` → `"2.7.2"`
- `utils/config.py` — `PLANNER_MAX_TOKENS`: `768` → `1024`
- `core/plannd.py` — step prompt: "2 to 5" → "2 to 8"
- `core/orchestrator.py` — plan cap: 5 → 8

---

## [v2.7.1] - 2026-03-29

### Fixed — Peer CLI Delegation + Shell Safety

#### Peer CLI Delegation Pipeline

- **"Ask Claude" bypassed plannd** (`main.py`): Added peer directive regex gate before `_try_daemon_plan()`. If the user prompt matches `\b(ask|call|have|tell|use|get|let)\s+(claude|gemini|qwen)\b`, the request skips plannd and goes directly to `run_agent()` so `_detect_peer_delegation` fires on the original message.

- **Wrong task sent to peer** (`core/agent.py`): Removed the `for _hm in reversed(history)` loop that scanned old history messages to override `_orig_goal`. The current `user_message` is now always used as-is, preventing stale tasks from resumed sessions from being forwarded to Claude instead of the actual request.

- **Claude asked for permission instead of writing code** (`core/agent.py`, `core/peer_cli.py`): Added `_FORMAT_INSTRUCTIONS` constant injected into every peer delegation prompt (both direct and escalation paths). Instructs the peer: "You are responding to an automated system. Do NOT ask for permission. Do NOT ask clarifying questions. Act immediately." Includes exact `**\`filename.py\`**` + triple-backtick output format that `_auto_apply_peer_code` parses.

- **Peer prompt now includes project files** (`core/agent.py`): When files exist in the working context, the delegated prompt now includes their current content so the peer CLI can read and reason about the codebase before writing code.

- **`_auto_apply_peer_code` fallback** (`core/agent.py`): Added secondary pattern matching for bare triple-backtick blocks (no filename header) — infers filename from the original task context when the peer omits the `**\`filename\`**` header line.

- **Duplicate `Run:` steps merged incorrectly** (`core/orchestrator.py`): `_postprocess_plan` now skips the file-merge deduplication logic for steps that start with `Run` — they are appended as-is so tests and scripts can be run multiple times.

- **Planner invented capabilities** (`core/plannd.py`): Added Rule 7 to PLANNER_PROMPT: "Never invent capabilities. Step descriptions must only reflect what the user explicitly described. Do not assume function arguments, test input values, or script features not mentioned in the user's request."

- **Malformed tool JSON silently dropped** (`core/agent.py`): After `parse_tool_call` returns None, if `<tool>` is present in the response, an explicit retry is triggered with a corrective message rather than falling through to the no-tool path.

- **Wrong retry context** (`main.py`): Retry steps now include the filename that failed, the previous result, and an explicit instruction to use `write_file` — preventing the agent from re-running a different or unrelated step on retry.

- **No-text-before-tool rule** (`prompts/system_prompt.py`): Strengthened from "Respond with exactly one tool call" to "NO TEXT BEFORE THE TOOL CALL — not even one word."

- **Step scope leakage** (`prompts/system_prompt.py`): Added rule "Current step is your ONLY scope. Never create or modify files not required by the Current step."

- **`2>&1` in follow-up pytest command** (`core/agent.py`): Removed `2>&1` from the auto-generated test follow-up shell command.

- **`max_steps` too low** (`utils/config.py`): Raised from `6` → `10` to accommodate multi-file tasks without hitting the step cap prematurely.

#### Shell Safety Model

- **Removed shell metacharacter blocklist** (`tools/shell_tools.py`): Deleted `SHELL_METACHARACTERS`, `validate_command_structure()`, and the hard `[ERROR] Command blocked` return. All commands — including those with `&&`, `|`, `;`, `2>&1` — now flow through the user confirmation prompt instead of being rejected outright.

- **Confirmation is universal**: Every command goes through `is_dangerous()` (explicit warning for `rm`, `curl`, `wget`, etc.) then `confirm_shell` (user approval prompt). YOLO mode bypasses both checks.

### Changed

- `utils/config.py` — `max_steps`: `6` → `10`
- Shell model: metacharacter blocklist → consent-based (confirm all, warn on dangerous)

---

## [v2.7.0] - 2026-03-25

### Added — Three-Model Architecture + DeepSeek Planner Daemon

#### New Components
- **`core/plannd.py`** — Planner daemon: runs `DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M` on port 8081 as a
  dedicated task-planning model. Listens on Unix socket `~/.codey-v2/plannd.sock`. Accepts raw user
  prompts, returns numbered step lists for the 7B execution model to work through one at a time.
- **`core/planner_client.py`** — Async socket client for plannd. Used by daemon to send planning
  requests and receive step lists. Raises `ConnectionRefusedError` if plannd is not running (silent
  fallback).

#### Architecture Changes
- **Three-daemon architecture**: `codeyd2` (main daemon, Qwen 7B on port 8080) + `plannd`
  (DeepSeek planner on port 8081) + embed server (nomic-embed on port 8082). All three start/stop
  together via `codeyd2 start` / `codeyd2 stop`.
- **`core/daemon.py`** — `_handle_command()` wired to plannd via `send_plan_request_async()`.
  45-second timeout with full silent fallback chain. `plan_only=True` flag prevents double execution:
  daemon returns the plan without queuing tasks, main.py executes each step locally.
- **`main.py`** — `_try_daemon_plan()` and `_run_with_plan()` added. `send_command()` was already
  defined but was never called for planning; this wiring fix is what enables the end-to-end planner
  flow.
- **`core/daemon.py` `send_command()`** — socket timeout increased from 30 s to 60 s to accommodate
  DeepSeek inference latency on CPU.

#### Memory-Mapping Fixes
- **`utils/config.py`** — `QWEN_7B_MMAP = True`, `QWEN_7B_MLOCK = False` added. Explicit config
  for 7B mmap behaviour rather than relying on llama.cpp defaults.
- **`core/loader_v2.py`** — Passes `--mmap` / `--no-mmap` explicitly based on config. Critical
  fix: `--no-mlock` does NOT exist in this llama.cpp build. Passing it would crash the server
  silently. The fix: omit `--mlock` entirely (llama.cpp default is mlock-off). Only pass `--mlock`
  when explicitly enabled via `QWEN_7B_MLOCK=1`.

#### Changed
- `codeyd2` — `start` and `stop` commands manage plannd lifecycle. `status` shows mmap state and
  health-checks all three model ports (8080, 8081, 8082).
- `utils/config.py` — version bumped: `2.6.9` → `2.7.0`

---

## [v2.6.10] - 2026-03-18
### Added
- Advanced context management (better token efficiency, phase-aware handling)
- Anti-babbling / self-awareness mechanisms (prevents repetitive or off-track loops)
- Stronger persistent memory across sessions

### Fixed
- Streaming response hangs
- Code leakage in agent outputs
- Session staleness issues



## [2.6.9] - 2026-03-17

### Removed — Single-Model Architecture

Removed the dual-model hot-swap system. Codey-v2 now runs exclusively on the
primary Qwen2.5-Coder-7B model. The router and secondary model added complexity
(SIGSTOP/SIGCONT caching, routing heuristics, cooldown logic) that caused subtle
failures (e.g. the 1.5B model timing out on tasks it couldn't handle) with
minimal practical benefit — the 7B model handles all tasks including short
conversational exchanges.

#### Removed

- `core/router.py` — `ModelRouter` class and `route_task()` routing logic
  (replaced with tombstone file)
- `utils/config.py` — `SECONDARY_MODEL_PATH` and `ROUTER_CONFIG` config keys
- `core/loader_v2.py` — `load_secondary()`, SIGSTOP/SIGCONT pause-based caching
  (`_stopped_servers` dict), and all hot-swap unload/resume logic
- `core/inference_v2.py` — `get_router()` import and auto-routing; the `model`
  parameter is now a no-op (always uses primary)
- `main.py` — `--ft-model` no longer offers `"1.5b"` / `"both"` choices;
  `--lora-model` no longer offers `"secondary"` choice

#### Changed

- `core/loader_v2.py` — `ModelLoader` simplified: single model, `unload()` now
  calls `stop()` directly instead of SIGSTOP; no stopped-server cache
- `core/inference_v2.py` — removed router dependency; always calls
  `loader.ensure_model()` with no model-type argument
- `utils/config.py` — version bumped: `2.6.8` → `2.6.9`

---

## [v2.6.8] - 2026-03-17

### Added — Phase 8: Adaptive Depth + Thermal Awareness

#### `core/recursive.py` — `get_adaptive_depth()`

- New function `get_adaptive_depth(requested_depth)` adjusts recursion depth
  based on device thermal and battery state read from `THERMAL_CONFIG`.
- Rules (in priority order):
  - `temp >= temp_critical` (default 90°C) → force depth 0 (no recursion)
  - `temp >= temp_warn` (default 75°C) → cap depth at 1
  - `battery <= batt_critical` (5%) and not charging → force depth 0
  - `battery <= batt_low` (15%) and not charging → cap depth at 1
  - Charging or cool → use `requested_depth` as-is
- `get_adaptive_depth` is called by `recursive_infer()` to replace the
  hard-coded `max_depth` argument, so hot devices silently degrade to faster
  single-pass inference instead of timing out.

#### `utils/config.py` — `THERMAL_CONFIG`

Added `THERMAL_CONFIG` dict with tunable thresholds:

```python
THERMAL_CONFIG = {
    "enabled": True,
    "warn_after_sec": 300,        # 5 min — log thread-reduction warning
    "reduce_threads_after_sec": 600,  # 10 min — drop to min_threads
    "min_threads": 2,
    "original_threads": 4,        # set from MODEL_CONFIG at startup
    "temp_critical": 90,          # °C — skip recursion entirely
    "temp_warn": 75,              # °C — cap recursion depth to 1
    "batt_critical": 5,           # % — skip recursion if not charging
    "batt_low": 15,               # % — cap depth to 1 if not charging
}
```

#### `core/daemon.py` — thread reduction loop

Daemon background thread monitors elapsed inference time and reduces
`MODEL_CONFIG["n_threads"]` to `THERMAL_CONFIG["min_threads"]` after
`reduce_threads_after_sec` of continuous inference — prevents sustained
CPU saturation from overheating the device.

### Changed
- `utils/config.py` — Version bumped: `2.6.7` → `2.6.8`

---

## [v2.6.7] - 2026-03-17

### Changed — Phase 7: Cleanup & Simplification

Phase 7 removed dead code paths and simplified the inference stack that
accumulated across Phases 1–6.

- **Removed legacy `build_system_prompt()` body** — reduced to a one-line
  wrapper around `build_recursive_prompt(phase="draft")`. All internal call
  sites already use `build_recursive_prompt` directly (Phase 3).
- **Removed duplicate `learn_from_file` call** from `execute_tool()` —
  it was called once in `execute_tool` and again in the `run_agent` loop
  after tool execution, causing double-learning per write. Kept only the
  post-execution call in the agent loop.
- **Consolidated `_action_kws` list** — `orchestrator.is_complex` and
  `agent.run_agent` both maintained separate action keyword lists that
  had drifted out of sync. Aligned them and added missing verbs
  (`verify`, `validate`, `confirm`, `replace`, `rename`, `swap`).
- **Removed stale `peer_cli.escalate()` history loop** — a `for _hm in
  reversed(history)` scan that could replace the current user task with
  a stale message from a resumed session. Always use `user_message` directly.
- **Cleaned `__pycache__` guard** in daemon start script.

### Changed
- `utils/config.py` — Version bumped: `2.6.6` → `2.6.7`




## [2.6.6] - 2026-03-17

### Added — Phase 6: Dedicated Embedding Server (Option C)

Phase 6 replaces the slow 7B-model embedding path with a purpose-built
encoder model running as a permanent, separate process.  Building the full
KB vector index now takes ~3 minutes instead of ~3 hours on-device.

#### New file: `core/embed_server.py`

- `EmbedServer` class — manages a dedicated `llama-server` subprocess for
  embeddings only.  Runs `nomic-embed-text-v1.5` (80 MB Q4, 2048 ctx,
  768-dim) on **port 8082** with `--embedding --pooling mean`,
  `-c 2048`, `-t 4`, `--ubatch-size 2048`.  Distinct from the 7B generation
  server — never evicted by model hot-swapping.
- `start_embed_server()` / `stop_embed_server()` — public helpers; both
  idempotent and safe to call multiple times.
- Startup: waits up to 30 s for `/health` to respond; logs to
  `~/.codey-v2/embed-server.log` on failure.
- Graceful stop on daemon shutdown; `pkill -f llama-server` from `codeyd2
  stop` also catches the embed server process.

#### Changes to `utils/config.py`

- `EMBED_MODEL_PATH` — path to embed GGUF (env: `CODEY_EMBED_MODEL`,
  default: `~/models/nomic-embed/nomic-embed-text-v1.5.Q4_K_M.gguf`)
- `EMBED_SERVER_PORT = 8082` — overridable via `CODEY_EMBED_PORT`

#### Changes to `tools/kb_semantic.py`

- `_LLAMA_PORT` default changed from `8080` → `8082` (the embed server
  port).  Priority: `CODEY_EMBED_PORT` > `CODEY_LLAMA_PORT` > `8082`.
- Both `build_semantic_index()` and `semantic_search()` now automatically
  connect to the dedicated embed server — no code change required.

#### Changes to `core/daemon.py`

- `_main_loop()` starts the embed server before the main `while` loop.
  Logs `"Embed server ready on port 8082"` on success or
  `"Embed server unavailable — BM25-only KB search active"` on failure
  (missing model file, binary not found, etc.) — never blocks daemon startup.
- `finally` block stops the embed server on clean shutdown.
- 30-second watchdog auto-restarts dead embed server during main loop.

#### Hybrid coverage: BM25 + vector

| Property | 7B generation model | nomic-embed-text-v1.5 |
|----------|---------------------|-----------------------|
| Size | ~4 GB | ~80 MB |
| Max context | 32k | 2048 |
| Embedding speed | ~3 s/chunk | ~50 ms/chunk |
| 3777-chunk index build | ~3 hours | **~3 min** |
| Vector dimension | 3584-d | 768-d |

nomic-embed has a hard 2048-token context limit baked into its GGUF metadata.
92.6% of chunks (3498/3777) get hybrid BM25+vector search; the remaining
7.4% (279 chunks exceeding 2048 tokens) use BM25 keyword fallback — still
searchable, just without cosine similarity ranking.

768-d vectors are stored in `knowledge/embeddings/vectors.npy` alongside
`vectors.meta.json` (records backend name + dimension so a mismatch is caught
at query time rather than producing silent garbage results).

#### 7B model optimizations (v2.6.6)

- Context: 8192 → **32768** (q4_0 KV cache saves ~950 MB vs q8_0)
- Threads: 4 → **6** (S24 Ultra has 12 cores — 50% utilization)
- Batch size: 256 → **1024** (faster prompt processing)
- KV cache type: q8_0 → **q4_0** (enables 32k ctx within 11 GB RAM)
- Flash attention: **enabled** (`--flash-attn on`)

#### One-time rebuild after upgrade

```bash
# Restart daemon (clears __pycache__ + starts embed server automatically)
codeyd2 stop && codeyd2 start
sleep 20

# Rebuild semantic index (~3 min with nomic on port 8082)
cd ~/codey-v2
python3 -c "from tools.kb_semantic import build_semantic_index; build_semantic_index()"
# writes vectors.npy at 768-dim (nomic-embed-text-v1.5)
```

### Changed
- `utils/config.py` — Version bumped: `2.6.5` → `2.6.6`

---

## [2.6.5] - 2026-03-17

### Added — Phase 5: Skill Loading + External Repos

Phase 5 adds dynamic skill injection into the system prompt. When Codey
receives a task, it now searches the indexed skill repositories for expert
prompt patterns that match the request and injects them as a `## Relevant
Skills` context layer alongside the existing RAG documentation.

#### New file: `core/skills.py`

- `load_relevant_skills(user_message, budget_chars=800)` — queries the KB
  with a skill-biased prefix (`"skill template pattern: <task>"`) to surface
  skill definitions over generic documentation chunks; returns a
  `## Relevant Skills` block or `""` if nothing relevant or no repos indexed
- `list_available_skills()` — returns names of cloned skill repos under
  `knowledge/skills/`; used for status reporting
- Guards against `knowledge/skills/` being absent or empty — returns `""`
  silently so the agent is never blocked if skill repos aren't set up
- All paths wrapped in `try/except` — never raises

#### Changes to `prompts/layered_prompt.py`

**`_build_draft_prompt()` — skills layer added:**
- After the RAG retrieval block, calls `load_relevant_skills(user_message)`
- If a non-empty block is returned, adds it at `priority=3` (same bucket as
  RAG and repo map — evicted before files if budget is tight)
- Wrapped in `try/except` — skills failure is silent and non-blocking

#### How it works end-to-end

```
User: "review core/agent.py for bugs"
  → _build_draft_prompt()
      → retrieve("review core/agent.py bugs")        → ## Reference Material (docs)
      → load_relevant_skills("review core/agent.py…") → ## Relevant Skills (skill patterns)
  → System prompt includes: docs + skill template for code review
  → Model follows the expert skill format (ISSUES / SUGGESTIONS / VERDICT)
```

#### Skill repos (set up via `tools/setup_skills.sh`)

| Repo | Purpose |
|------|---------|
| awesome-claude-skills | Curated skill definitions for common dev workflows |
| superpowers | Advanced multi-tool orchestration patterns |
| skil | Formal skill schema (Anthropic) |
| notebooklm-skill | Document analysis + summarization patterns |
| marketingskills | Content/docs generation patterns |

#### Before vs. after

| Aspect | Before Phase 5 | After Phase 5 |
|--------|---------------|---------------|
| Skill awareness | None — model improvises format | Expert skill patterns injected if available |
| System prompt layers | identity, prefs, project, RAG, files | + skills layer at priority=3 |
| With empty skills dir | N/A | Silent `""` return — no change to behaviour |
| Budget impact | — | +0–800 chars (evicted first among p=3 if tight) |

### Changed
- `utils/config.py` — Version bumped: `2.6.4` → `2.6.5`

---

## [2.6.4] - 2026-03-17

### Added — Phase 4: Recursive Planning + Orchestration

Phase 4 completes the recursive loop for multi-step tasks.  Plans now
self-critique with KB retrieval, and each subtask in the execution queue
receives targeted knowledge-base context specific to what that step needs.

#### Changes to `core/orchestrator.py`

**`plan_tasks()` — self-critiquing plans with retrieval:**
- Retrieves relevant KB docs (`budget_chars=1200`) before building the planning
  prompt so the model plans with known patterns and API references
- Calls `recursive_infer(task_type="plan", max_depth=2, stream=False)` so the
  plan goes through one self-critique + refine cycle using `CRITIQUE_PLAN`
  (checks step count, ordering, redundancy, completeness)
- Falls back to plain `infer()` transparently if recursion is unavailable
- Controlled by `RECURSIVE_CONFIG["recursive_for_plans"]` (default `True`)

**`run_queue()` — per-subtask RAG retrieval:**
- For each pending subtask, calls `classify_breadth_need(task.description)` to
  determine complexity
- For `standard` or `deep` subtasks: retrieves targeted KB context
  (`budget_chars=1200`) and appends it to the subtask prompt before calling
  `run_agent()`.  Each subtask gets context relevant to its specific focus
  (e.g. step 1 gets Flask API docs; step 2 gets unittest patterns)
- `minimal` subtasks skip retrieval — no overhead for trivial steps
- Fully try/except guarded — retrieval failure is silent and non-blocking

#### Before vs. after

| Aspect | Before Phase 4 | After Phase 4 |
|--------|---------------|---------------|
| Plan quality | Single-pass `infer()` | Draft→Critique→Refine + RAG |
| Plan context | Git-repo flag only | + Relevant KB docs |
| Subtask context | File context + domain guidance | + Targeted per-subtask KB retrieval |
| Failure mode | Silent — uses whatever plan model produces | Same (all wrapped in try/except) |

### Changed
- `utils/config.py` — Version bumped: `2.6.3` → `2.6.4`

---

## [2.6.3] - 2026-03-17

### Added — Phase 3: Layered System Prompts

Phase 3 introduces a phase-aware system prompt architecture.  Each stage of the
recursive inference loop now receives context optimised for what that stage needs,
rather than a static system prompt that wastes tokens on irrelevant information.

#### New Files
- `prompts/layered_prompt.py` — Layered prompt builder with two exports:
  - `LayeredPrompt` class — priority-managed context assembler with budget-based
    eviction.  Layers sorted by importance (lower priority number = kept first).
    Required layers are never evicted.  Final output maintains insertion order for
    coherent reading.
  - `build_recursive_prompt(user_message, phase, ...)` — Phase-aware system prompt
    factory.  Drop-in replacement for `build_system_prompt()`.

#### Phase-aware context composition
```
phase="draft"    → Full context (identical to old build_system_prompt — no regression)
                   Priority stack:
                     0 SYSTEM_PROMPT       (required)
                     1 User preferences
                     2 Project memory / CODEY.md
                     3 Repo map
                     3 Retrieved KB docs (RAG, Phase 1)
                     4 Loaded files

phase="critique" → Lean context — drops project, files, history
                   Priority stack:
                     0 Critique instructions  (required)
                     1 Prior draft to review  (required, embedded in system prompt)
                   Benefit: saves ~3000 tokens vs using full system prompt

phase="refine"   → Full context minus history — adds critique summary
                   Priority stack:
                     0 SYSTEM_PROMPT       (required)
                     1 User preferences
                     2 Project memory / CODEY.md
                     2 Issues to Fix (critique summary, required)
                     3 Repo map
                     3 Targeted retrieved docs (NEED_DOCS, if any)
                     4 Loaded files
                   Benefit: history dropped (~1000 tokens freed); critique
                   acts as the "memory" of what to fix
```

#### Context savings per request (typical standard-depth run)
| Pass       | Before Phase 3        | After Phase 3          |
|------------|-----------------------|------------------------|
| Draft      | full system (~3K tok) | full system (~3K tok)  |
| Critique   | full system (~3K tok) | lean (~0.5K tok)       |
| Refine     | full + history (~4K)  | full − history (~3K)   |
| **Total**  | ~10K tokens           | ~6.5K tokens           |

#### Improved refine quality
The refine pass previously used `[*messages + draft + refine_instruction]` which
included the full conversation history.  Phase 3 instead generates a fresh response
to the original task with the critique embedded in the system prompt.  The model
produces a cleaner result (no history noise, full context budget available).

### Changed
- `core/agent.py` — `build_system_prompt()` is now a thin wrapper around
  `build_recursive_prompt(message, phase="draft")`.  The two call sites in
  `run_agent()` now call `build_recursive_prompt()` directly.  Backward
  compatible — external code calling `build_system_prompt()` still works.
- `core/recursive.py` — Critique and refine message construction updated to use
  `build_recursive_prompt(phase="critique")` and `build_recursive_prompt(phase="refine")`.
  Removed direct `select_critique_prompt` import (now handled in layered_prompt.py).
- Version bumped: `2.6.2` → `2.6.3`

---

## [2.6.2] - 2026-03-17

### Added — Phase 2: Core Recursive Inference

This phase introduces a self-refine loop so the model reviews and improves
its own output before returning it. The model generates a draft, critiques it,
then refines — stopping early when quality is acceptable.

#### New Files
- `core/recursive.py` — Recursive inference engine. `recursive_infer()` wraps
  `infer()` with a draft → critique → refine loop. Key functions:
  - `recursive_infer()` — main entry point, returns final response string
  - `classify_breadth_need()` — classifies task as "minimal" / "standard" / "deep"
    to determine recursion depth (0 / 1 / 2 critique+refine cycles)
  - `passes_quality_check()` — quality gate: extracts X/10 rating or checks for
    critical issue markers; returns True if draft is acceptable
  - `extract_rating()` — regex-based X/10 parser
  - `extract_doc_needs()` — extracts NEED_DOCS markers for targeted KB retrieval
- `prompts/critique_prompts.py` — Self-critique prompt templates:
  - `CRITIQUE_CODE` — for write_file, patch_file, code generation tasks
  - `CRITIQUE_TOOL` — for tool call validation
  - `CRITIQUE_PLAN` — for orchestration plan review
  - `select_critique_prompt(task_type)` — selects appropriate template

#### Inference Flow (Phase 2)
```
Step 1 of ReAct loop (non-QA tasks):
  classify_breadth_need(user_message)
    "minimal" → infer() (single pass, no change)
    "standard" → recursive_infer(..., max_depth=1)
                   Draft → Critique → (if quality gate passes: done)
                                    → Refine → done
    "deep"    → recursive_infer(..., max_depth=2)
                   Draft → Critique → Refine → Critique → done

Steps 2+ of ReAct loop (tool reactions):
  infer() — single pass (no recursion, already reacting to concrete feedback)
```

#### Quality Gate
- Looks for `X/10` rating in critique text
- If rating ≥ 7/10 (threshold × 10): skip refinement — accept draft
- If no numeric rating: check for critical markers (`"syntax error"`,
  `"missing import"`, `"will crash"`, etc.) — any match triggers refinement
- The model can emit `NEED_DOCS: <topic>` to trigger targeted KB retrieval
  before the refine pass (injects up to 1200 chars of relevant docs)

#### Performance characteristics
- Best case (quality passes after draft): 2 infer calls (+1 critique, no refine)
- Standard depth-1: up to 3 calls (draft + critique + refine)
- Deep depth-2: up to 5 calls (draft + 2×(critique+refine))
- All extra calls are wrapped in `try/except` — failure falls back to plain `infer()`
- Disable entirely: `RECURSIVE_CONFIG["enabled"] = False` in `utils/config.py`

### Changed
- `utils/config.py` — Added `RECURSIVE_CONFIG` with tunable knobs:
  `enabled`, `max_depth` (default 1), `quality_threshold` (0.7),
  `recursive_for_writes`, `recursive_for_plans`, `recursive_for_qa`,
  `critique_budget` (512 tokens), `retrieval_budget` (1200 chars).
- `core/agent.py` — ReAct loop step 1 now calls `recursive_infer()` for
  non-QA tasks with breadth ≠ "minimal". Steps 2+ use plain `infer()`.
  Import of `RECURSIVE_CONFIG` added. Fully backward-compatible — disabled
  path is identical to previous behavior.
- Version bumped: `2.6.1` → `2.6.2`

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
| 2.7.1 | 3.12+ | Latest | Latest stable | Qwen2.5-Coder-7B + DeepSeek-R1-1.5B + nomic-embed |
| 2.7.0 | 3.12+ | Latest | Latest stable | Qwen2.5-Coder-7B + DeepSeek-R1-1.5B + nomic-embed |
| 2.6.9 | 3.12+ | Latest | Latest stable | Qwen2.5-Coder-7B |
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
