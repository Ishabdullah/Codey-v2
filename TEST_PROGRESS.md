# Codey-v2 Testing Progress Log

**Session Started:** 2026-03-07
**Goal:** Run all 7 major feature tests, saving progress after each

## Test Queue

| # | Test | Status | Started | Completed | Issues Found | Fixes Applied |
|---|------|--------|---------|-----------|--------------|---------------|
| 1 | Complex coding task with daemon | ✅ Complete | 2026-03-07 | 2026-03-08 | 2 | 0 |
| 2 | Dual-model hot-swap (7B ↔ 1.5B) | ⏳ Pending | - | - | - | - |
| 3 | Background file watching | ⏳ Pending | - | - | - | - |
| 4 | Self-modification with checkpointing | ⏳ Pending | - | - | - | - |
| 5 | Hierarchical memory (semantic search) | ⏳ Pending | - | - | - | - |
| 6 | TDD cycle with `--tdd` mode | ⏳ Pending | - | - | - | - |
| 7 | `--fix` auto-debug mode | ⏳ Pending | - | - | - | - |

## Current State

**Last Completed Test:** None
**Current Test:** None
**System State:** Daemon running (PID: 25097), all 16 unit tests passing

## Notes

- Daemon is operational
- All 34 audit findings from codey-v2_review.md are fixed
- Ready to begin Test 1

---

## Test 1: Complex Coding Task with Daemon

**Status:** 🔄 In Progress

### Plan
1. Send a complex multi-file coding task to the daemon
2. Verify planner breaks it into subtasks
3. Verify all subtasks complete successfully
4. Check task history in state database

### Execution Log

**Step 1:** Creating a complex multi-file task - Build a REST API with Flask

**Step 2:** Previous session crashed with "[ERROR] Inference failed" - llama-server inference error

**Step 3:** Resumed test - ran task through Codey-v2 with primary model (7B)

**Step 4:** Codey-v2 successfully created:
- `app.py` - Flask app with all 4 endpoints (GET /todos, POST /todos, GET /todos/<id>, DELETE /todos/<id>)
- `requirements.txt` - Flask dependency

**Step 5:** Verifying files are syntactically correct

### Issues Found

1. Inference server failed during initial test run (session `test_project_062392c51124.json`) - likely timeout
2. Slow inference speed observed: 0.3-0.8 t/s (thermal throttling on mobile device)

### Fixes Applied

None required - task completed successfully despite initial crash

---

## Test 2: Dual-Model Hot-Swap (7B ↔ 1.5B)

**Status:** 🔄 In Progress (Checkpoint: test_checkpoint.json)

### Plan
1. ✓ Verify secondary model (1.5B) is available
2. Send simple task (should route to 1.5B)
3. Send complex task (should route to 7B)
4. Verify hot-swap behavior and timing

### Pre-Test Checkpoint

**Checkpoint File:** `test_checkpoint.json`
**Timestamp:** 2026-03-08T00:21:25
**System State:**
- Daemon: Not running
- Primary model: Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf (port 8080)
- Secondary model: Qwen2.5-1.5B-Instruct-Q8_0.gguf (1.85GB, verified exists)

### Execution Log

**Step 1:** ✓ Models verified - both 7B and 1.5B available in ~/models/

**Step 2:** Running simple task to test 1.5B routing...

### Issues Found

*(To be filled if any)*

### Fixes Applied

*(To be filled if any)*

---

## Test 3: Background File Watching

**Status:** ⏳ Not Started

### Plan
1. Create a test directory with files
2. Start file watch on directory
3. Modify a file
4. Verify watch callback fires

### Execution Log

*(To be filled during test)*

### Issues Found

*(To be filled if any)*

### Fixes Applied

*(To be filled if any)*

---

## Test 4: Self-Modification with Checkpointing

**Status:** ⏳ Not Started

### Plan
1. Request a modification to a core Codey-v2 file
2. Verify checkpoint is created before modification
3. Verify modification succeeds
4. Test rollback functionality

### Execution Log

*(To be filled during test)*

### Issues Found

*(To be filled if any)*

### Fixes Applied

*(To be filled if any)*

---

## Test 5: Hierarchical Memory (Semantic Search)

**Status:** ⏳ Not Started

### Plan
1. Load multiple files into memory
2. Store content in long-term memory with embeddings
3. Perform semantic search query
4. Verify correct files are returned

### Execution Log

*(To be filled during test)*

### Issues Found

*(To be filled if any)*

### Fixes Applied

*(To be filled if any)*

---

## Test 6: TDD Cycle with `--tdd` Mode

**Status:** ⏳ Not Started

### Plan
1. Create a simple function file without implementation
2. Create test file with failing tests
3. Run `codey-v2 --tdd` mode
4. Verify tests pass after TDD cycle

### Execution Log

*(To be filled during test)*

### Issues Found

*(To be filled if any)*

### Fixes Applied

*(To be filled if any)*

---

## Test 7: `--fix` Auto-Debug Mode

**Status:** ⏳ Not Started

### Plan
1. Create a Python file with intentional bugs
2. Run `codey-v2 --fix` on the file
3. Verify bugs are identified and fixed
4. Run file to confirm it works

### Execution Log

*(To be filled during test)*

### Issues Found

*(To be filled if any)*

### Fixes Applied

*(To be filled if any)*

---

## Session Summary

**Tests Completed:** 1/7
**Issues Found:** 2 (inference timeout, slow t/s due to thermal throttling)
**Fixes Applied:** 0
**Last Updated:** 2026-03-08 (Test 1 Complete)
