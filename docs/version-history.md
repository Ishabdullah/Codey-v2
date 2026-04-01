# Version History

## v2.0.0 — Initial Public Release (2026-04-01)

The full feature set of Codey-v2 — three-model architecture, four-tier memory,
multi-peer escalation, shell consent model, design-only planning phase, hybrid
RAG retrieval, thermal management, voice, fine-tuning pipeline, and security
hardening. See [CHANGELOG.md](../CHANGELOG.md) for the complete feature list.

---

## Pre-release Development Notes

> The following entries document significant internal milestones during development.

## v2.7.0 — Context Management Rewrite

- **Smarter context compression**: Trigger moved from 75% → 55% of context window; drop target is 40%, giving real headroom for long sessions.
- **Sliding window drop**: Oldest unpinned turns are dropped first — no model call needed for the drop itself.
- **Pinned messages**: `write_file`, `patch_file`, `[ERROR]`, shell results, and existing summaries are never dropped or re-summarized.
- **0.5B micro-summary**: After dropping turns, the 0.5B model on port 8081 generates a ≤100-word "Previously:" summary of only what was dropped. Best-effort — silently skipped if port 8081 is unreachable.
- **No re-summarization**: An existing `[CONVERSATION SUMMARY]` is pinned and never fed back into another summary pass.
- **Fixed content truncation**: Removed the `[:300]` message truncation that was destroying tool output before the summarizer could see it.
- **Planner timeout increased**: `asyncio.wait_for` raised from 45 s → 180 s; HTTP timeout raised from 30 s → 165 s to match.

## v2.6.6 — Dedicated Embedding Server

- `nomic-embed-text-v1.5` (80 MB Q4, 768-dim) runs as a permanent separate process on port 8082.
- Hybrid BM25 + vector search with RRF merging — +15–25% retrieval recall over BM25 alone.
- 92.6% of chunks get vector embeddings; remainder falls back to BM25.
- Auto-started and watchdog-monitored by `codeyd2 start`.

## v2.6.5 — Skill Loading

- `core/skills.py` searches indexed skill repos for patterns matching the current task.
- Matching skill templates are injected into the system prompt automatically.
- `bash tools/setup_skills.sh` clones and indexes curated skill repos.
- Silent no-op if `knowledge/skills/` is empty.

## v2.6.4 — Recursive Planning

- Orchestrator uses `recursive_infer(task_type="plan")` — every multi-step plan goes through draft → critique → refine.
- Plan-time RAG: relevant KB docs are retrieved and injected into the planning prompt.
- Per-subtask retrieval: each item in the execution queue gets targeted KB context.

## v2.6.3 — Layered Context System

- Phase-aware prompts: each inference stage (draft, critique, refine) gets only the context it needs.
- `LayeredPrompt` class drops lower-priority blocks first when the budget is tight; critical blocks are never evicted.
- ~35% token reduction on typical recursive calls vs. Phase 2.

## v2.6.2 — Recursive Self-Refinement

- Draft → Critique → Refine on every non-trivial coding task.
- `classify_breadth_need()` auto-detects complexity: Q&A = single pass; code edits = 1 cycle; multi-file = 2 cycles.
- Quality gate: if the model rates its own output ≥ 7/10, refinement is skipped.
- `NEED_DOCS` trigger: model emits `NEED_DOCS: <topic>` during critique to request a targeted KB lookup before the refine pass.

## v2.6.1 — Knowledge Base + RAG

- `knowledge/` directory stores docs, APIs, patterns, and skill repos as searchable chunks.
- Every inference call searches the KB and injects up to ~600 tokens of relevant context.
- Dual backends: semantic search via `sentence-transformers`; BM25 keyword always active.

## v2.6.0 — Inference Pipeline Rewrite

- Fixed ChatML prompt formatting — root cause of ~70% of instruction-following failures.
- `/v1/chat/completions` with proper message arrays; llama-server applies the model's template.
- Context window 4K → 8K; max response tokens 1024 → 2048.
- Simplified from 3 backends (direct binding, Unix socket, TCP HTTP) to 1 reliable backend.
- Subtask file context passing: step 2 sees what step 1 wrote.
- Result validation catches false success claims from the model.

## v2.5.5 — Git Enhancements

- Branch management: `/git branches`, `/git branch <name>`, `/git checkout <name>`.
- Smart merge: `/git merge <branch>` with automatic conflict detection and resolution flow.
- AI commit messages: `/git commit` reads the diff and generates a message you review before it commits.
- Conventional commits: detects `feat:` / `fix:` style and matches it automatically.

## v2.5.4 — Peer Delegation Fixes

- "ask gemini/claude/qwen to X" now actually calls that peer and applies the result.
- Extended action keywords: "replace", "rename", "change", "ask", "call", etc.
- `patch_file` hints now include replace/rename/append guidance.

## v2.5.3 — Bug Fixes

- Agent loop after simple writes fixed: added `\nUser:` / `\nHuman:` / `\nA:` stop sequences.
- Fixed `extra_stop` tokens never reaching llama-server.
- Auto-lint now injects only errors to agent context (warnings go to terminal only).
- CPU monitor fixed with a 250 ms self-contained mini-sample.

## v2.5.2 — Static Analysis and Code Review

- Auto-lint after every Python file write; issues injected into agent context for self-correction.
- Pre-write syntax gate: Python files with broken syntax are blocked before they touch disk.
- `/review <file>` multi-linter scan (ruff / flake8 / mypy) with optional agent fix.

## v2.5.1 — Voice Interface

- TTS via `termux-tts-speak`; STT via `termux-speech-to-text`.
- `/voice on`, `/voice off`, `/voice listen`, `/voice rate`, `/voice pitch`.
- Settings persist across sessions.
- Requires Termux:API app + `pkg install termux-api`.

## v2.5.0 — Peer CLI Escalation and Enhanced Learning

- Auto-escalate to Claude Code, Gemini CLI, or Qwen CLI when retry budget is exhausted.
- `/peer` command for manual escalation; smart routing by task type.
- Crash detection for Android ARM64 native module failures.
- Natural language preference learning; expanded preference categories.
- CODEY.md sync: high-confidence preferences written to project Conventions section.

## v2.4.0 — Hybrid Inference Backend

- Direct llama-cpp-python + Unix socket HTTP + TCP HTTP fallback chain.
- Accurate architecture diagram; documented Termux constraints.

## v2.3.0 — Fine-tuning Support

- Export interaction data to JSONL for training.
- Unsloth Colab notebooks for off-device fine-tuning.
- LoRA adapter import with automatic backup and rollback.

## v2.2.0 — Machine Learning

- User preference learning from interaction history.
- Error pattern database: remembers errors and suggests fixes for similar problems.
- Strategy effectiveness tracking: learns which recovery strategies work best over time.

## v2.1.0 — Security and Reliability Hardening

- Shell metacharacter blocking (`;`, `&&`, `||`, `|`, backticks, `$()`, `${}`, etc.).
- Self-modification opt-in with checkpoint enforcement.
- LRU model cache; JSON parser improvements; hallucination detection.
- Context budget enforcement; orchestration conversational filters.

## v2.0.0 — Complete Rewrite

Seven-phase implementation: Daemon, Memory, Dual-Model, Planner, Checkpoints, Observability, Recovery.

## v1.0.0 — Original Codey

Session-based CLI with a ReAct agent loop. No persistence, no daemon, single model.
