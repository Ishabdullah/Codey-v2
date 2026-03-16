# Codey-v2 v2.6.0 — Critical Fixes & Architecture Corrections
**Date**: 2026-03-16
**Scope**: Inference pipeline rewrite, context expansion, subtask isolation fix, prompt trimming

---

## Issues Diagnosed (from live testing sessions)

### CRITICAL
- [x] **#1 — Wrong prompt format (no ChatML)**: Hybrid backend formats messages as `System: ...\nUser: ...\nAssistant:` but Qwen2.5-Coder expects ChatML (`<|im_start|>system\n...<|im_end|>`). Model doesn't recognize system instructions. Root cause of ~70% of failures.
- [x] **#2 — max_tokens=1024 too low**: A complete REST API file needs ~1500-2000 tokens in JSON-escaped form. Model is forced to write stubs.

### MAJOR
- [x] **#3 — Subtask isolation**: Each orchestrator subtask runs with empty history. Step 2 has no idea what step 1 wrote. test_api.py references functions that don't exist in app.py.
- [x] **#4 — System prompt too long**: 50 lines of rules for a 7B model. Most get ignored. Model can hold 5-7 rules max in working memory.
- [x] **#5 — No result validation**: Orchestrator marks "tests passed" as DONE when tests actually FAILED. Only checks for [INCOMPLETE] prefix, not [ERROR] or shell failure output.

### MODERATE
- [x] **#6 — Inference stack complexity**: Three backends (Direct, UnixSocket, TcpHttp) where only TcpHttp ever works on Termux. Dual-model router adds complexity for minimal benefit.
- [x] **#7 — Context budget math wrong**: BUDGET_RESPONSE=1296 but max_tokens=1024. System prompt uses ~800+ tokens, not the budgeted 700.

---

## Fixes Applied

### Fix #1 — ChatML prompt formatting (P0)
- **Files**: `core/inference_v2.py`, `core/inference_hybrid.py`
- **Change**: Rewrote all backends to use `/v1/chat/completions` endpoint with proper messages array. Removed manual `System:/User:/Assistant:` prompt formatting. llama-server now applies Qwen2.5-Coder's ChatML template automatically.
- **Status**: [x] DONE

### Fix #2 — Token limits & context expansion (P0)
- **Files**: `utils/config.py`, `core/memory.py`
- **Change**: `max_tokens` 1024→2048, `n_ctx` 4096→8192. Recalculated all memory budgets for 8K context. BUDGET_FILES doubled, BUDGET_RESPONSE aligned with max_tokens.
- **Status**: [x] DONE

### Fix #3 — Subtask file context passing (P1)
- **Files**: `core/orchestrator.py`
- **Change**: After each subtask completes, read files it created/modified and inject content into next subtask's prompt. Step 2 now sees step 1's actual code.
- **Status**: [x] DONE

### Fix #4 — System prompt trim (P1)
- **Files**: `prompts/system_prompt.py`, `core/orchestrator.py`
- **Change**: Cut system prompt from 50 to ~20 lines. Kept essential rules only. Moved domain-specific guidance (HTTP server pattern, sqlite, testing) into orchestrator's contextual subtask prompts.
- **Status**: [x] DONE

### Fix #5 — Result validation (P2)
- **Files**: `core/orchestrator.py`
- **Change**: run_queue() now checks task results for [ERROR] markers and validates shell output for FAILED/error patterns. False success claims are caught and marked as failed.
- **Status**: [x] DONE

### Fix #6 — Simplified inference stack (P3)
- **Files**: `core/inference_hybrid.py`, `core/inference_v2.py`
- **Change**: Removed DirectBindingBackend and UnixSocketBackend. Kept only TcpHttpBackend using /v1/chat/completions. Removed dual-model router dependency from inference path.
- **Status**: [x] DONE

### Fix #7 — Version bump & README
- **Files**: `utils/config.py`, `README.md`
- **Change**: Version 2.5.5→2.6.0. README updated with v2.6.0 changes.
- **Status**: [x] DONE
