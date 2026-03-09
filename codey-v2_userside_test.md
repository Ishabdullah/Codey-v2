# Codey-v2 Comprehensive User-Side Test Suite

**Version:** v2.4.0  
**Purpose:** Complete functional testing of all Codey-v2 systems and capabilities  
**Estimated Time:** 2-3 hours for full suite  
**Prerequisites:** Codey-v2 installed, models downloaded, daemon running

---

## Table of Contents

1. [Basic Functionality Tests](#1-basic-functionality-tests)
2. [CLI Commands Tests](#2-cli-commands-tests)
3. [File Operations Tests](#3-file-operations-tests)
4. [Shell & Security Tests](#4-shell--security-tests)
5. [Learning System Tests](#5-learning-system-tests)
6. [Fine-tuning Workflow Tests](#6-fine-tuning-workflow-tests)
7. [Hybrid Backend Tests](#7-hybrid-backend-tests)
8. [Memory & Context Tests](#8-memory--context-tests)
9. [Error Handling & Recovery Tests](#9-error-handling--recovery-tests)
10. [Edge Cases & Stress Tests](#10-edge-cases--stress-tests)

---

## 1. Basic Functionality Tests

### 1.1 Simple Query (Secondary Model)

**Command:**
```bash
codey2 "What is 2+2?"
```

**Expected Output:**
```
Auto-routed to secondary model
==================================================
Codey-v2: 2+2 equals 4.
==================================================
```

**Verification:**
- [ ] Response is correct
- [ ] Uses secondary (1.5B) model for simple query
- [ ] Response time < 5 seconds

---

### 1.2 Complex Task (Primary Model)

**Command:**
```bash
codey2 "Create a Flask REST API with user authentication and JWT tokens"
```

**Expected Output:**
```
Auto-routed to primary model
Planning subtasks...
  Execute this plan? [Y/n]:
==================================================
[Tool panels showing file creation]
==================================================
```

**Verification:**
- [ ] Uses primary (7B) model
- [ ] Triggers orchestration (multi-step plan)
- [ ] Creates appropriate files (app.py, auth.py, etc.)
- [ ] Files contain valid Python code

---

### 1.3 Interactive REPL Mode

**Command:**
```bash
codey2
```

**Expected Output:**
```
  ██████╗ ██████╗ ██████╗ ███████╗██╗   ██╗
 ██╔════╝██╔═══██╗██╔══██╗██╔════╝╚██╗ ██╔╝
 ...
Project: python · /home/user/myproject
Memory: CODEY.md found

You> 
```

**Verification:**
- [ ] Banner displays correctly
- [ ] Project type detected
- [ ] CODEY.md status shown
- [ ] REPL prompt appears

**Follow-up Commands:**
```
You> create a hello world function
You> /help
You> /learning
You> /exit
```

---

## 2. CLI Commands Tests

### 2.1 Version Check

**Command:**
```bash
codey2 --version
```

**Expected Output:**
```
Codey-v2 v2.4.0
```

**Verification:**
- [ ] Shows correct version (v2.4.0)

---

### 2.2 YOLO Mode (Skip Confirmations)

**Command:**
```bash
codey2 --yolo "create test.py with print('hello')"
```

**Expected Output:**
```
YOLO mode: confirmations disabled.
==================================================
[File created without confirmation prompt]
==================================================
```

**Verification:**
- [ ] YOLO mode message displayed
- [ ] No confirmation prompts shown
- [ ] File created successfully

---

### 2.3 Self-Modification Flag

**Command:**
```bash
codey2 --allow-self-mod "improve the JSON parser in core/agent.py"
```

**Expected Output:**
```
Self-modification enabled: Codey can modify its own source files (with checkpoints).
==================================================
[Checkpoint created message]
[Modification applied]
==================================================
```

**Verification:**
- [ ] Self-modification enabled message shown
- [ ] Checkpoint created before core file modification
- [ ] Core file modified successfully

---

### 2.4 Fine-tuning Export

**Command:**
```bash
codey2 --finetune --ft-days 30 --ft-quality 0.7 --ft-model both
```

**Expected Output:**
```
Preparing fine-tuning dataset...
Curating examples from last 30 days (min_quality=0.7)...
Curated X examples
Exported X examples to ~/Downloads/codey-finetune/codey-finetune-1.5b.jsonl
Exported X examples to ~/Downloads/codey-finetune/codey-finetune-7b.jsonl
Generated notebook: ~/Downloads/codey-finetune/codey-finetune-qwen-coder-1.5b.ipynb
Generated notebook: ~/Downloads/codey-finetune/codey-finetune-qwen-coder-7b.ipynb

╔══════════════════════════════════════════════════════════════════════════════╗
║                    Codey-v2 Fine-tuning Workflow                             ║
...
```

**Verification:**
- [ ] Dataset files created
- [ ] Notebooks generated
- [ ] Instructions displayed
- [ ] Files in ShareGPT format

---

### 2.5 Learning Status

**Command (in REPL):**
```
/learning
```

**Expected Output:**
```
Learning System Status

Preferences:
  test_framework: pytest [████████░░]
  naming_convention: snake_case [██████████]
  import_style: absolute [██████░░░░]

Error Database:
  Patterns: 15
  Occurrences: 42
  Fixed: 38
  Success Rate: 90.5%

Strategy Tracker:
  Strategies: 10
  Total Attempts: 127
  Overall Success: 87.4%
  Top Strategies:
    use_patch: 92% (45 attempts)
    install_dependency: 95% (30 attempts)
```

**Verification:**
- [ ] Preferences displayed with confidence bars
- [ ] Error database statistics shown
- [ ] Strategy tracker stats displayed

---

## 3. File Operations Tests

### 3.1 Create New File

**Command:**
```bash
codey2 "create a file called hello.py with a function that prints hello world"
```

**Expected Output:**
```
==================================================
📄 Written hello.py
==================================================
```

**Verification:**
- [ ] File created
- [ ] File contains valid Python
- [ ] Function prints "hello world"

**Check File:**
```bash
cat hello.py
```

---

### 3.2 Modify Existing File (Patch)

**Command:**
```bash
codey2 "add a docstring to the hello function in hello.py"
```

**Expected Output:**
```
==================================================
📝 Patched hello.py
--- a/hello.py
+++ b/hello.py
@@ -1,4 +1,6 @@
 def hello():
+    """Print hello world."""
     print("hello world")
==================================================
```

**Verification:**
- [ ] File patched (not rewritten)
- [ ] Diff displayed
- [ ] Docstring added

---

### 3.3 Read File Context

**Command (in REPL):**
```
/read hello.py
```

**Expected Output:**
```
✓ Loaded: hello.py (X chars)
```

**Verification:**
- [ ] File loaded into context
- [ ] `/context` shows file in memory

---

### 3.4 Undo File Changes

**Command (in REPL):**
```
/undo hello.py
```

**Expected Output:**
```
✓ Restored hello.py to previous version
```

**Verification:**
- [ ] File restored to previous version
- [ ] Docstring removed (from 3.2)

---

### 3.5 Diff File Changes

**Command (in REPL):**
```
/diff hello.py
```

**Expected Output:**
```
--- a/hello.py
+++ b/hello.py
@@ -1,4 +1,6 @@
 def hello():
+    """Print docstring."""
     print("hello world")
```

**Verification:**
- [ ] Colored diff displayed
- [ ] Shows all changes this session

---

## 4. Shell & Security Tests

### 4.1 Safe Shell Command

**Command:**
```bash
codey2 "list the files in the current directory"
```

**Expected Output:**
```
Run shell command: `ls -la`? [y/N]: y
==================================================
🔧 shell: ls -la
[output showing files]
==================================================
```

**Verification:**
- [ ] Confirmation prompt shown
- [ ] Command executes
- [ ] Output displayed

---

### 4.2 Shell Injection Prevention

**Command:**
```bash
codey2 "run: ls; rm -rf /"
```

**Expected Output:**
```
✗ Blocked unsafe command: `ls; rm -rf /`
[ERROR] Command blocked: Shell metacharacter ';' not allowed (prevents injection)
```

**Verification:**
- [ ] Command blocked
- [ ] Error message explains why
- [ ] No files deleted

---

### 4.3 Dangerous Command Confirmation

**Command:**
```bash
codey2 "delete the test.txt file"
```

**Expected Output:**
```
⚠  Potentially dangerous command: `rm test.txt`
Run shell command: `rm test.txt`? [y/N]:
```

**Verification:**
- [ ] Warning shown for dangerous command
- [ ] Confirmation required
- [ ] Can decline

---

### 4.4 Self-Modification Without Flag

**Command:**
```bash
codey2 "modify core/agent.py to add a print statement"
```

**Expected Output:**
```
[ERROR] Access denied: /home/codey-v2/core/agent.py is outside workspace. 
Enable self-modification with --allow-self-mod flag or ALLOW_SELF_MOD=1
```

**Verification:**
- [ ] Access denied
- [ ] Error message explains how to enable
- [ ] Core file NOT modified

---

### 4.5 Self-Modification With Flag

**Command:**
```bash
codey2 --allow-self-mod "add a comment to core/agent.py line 1"
```

**Expected Output:**
```
Self-modification enabled: Codey can modify its own source files (with checkpoints).
Checkpoint created before modifying core/agent.py
✓ Written core/agent.py
```

**Verification:**
- [ ] Checkpoint created
- [ ] Core file modified
- [ ] Checkpoint stored in ~/.codey-v2/checkpoints/

---

## 5. Learning System Tests

### 5.1 Preference Learning

**Setup:**
```bash
# Create test files with specific style
echo "import pytest

def test_example():
    assert True" > test_style.py
```

**Command:**
```bash
codey2 "create another test file following the project style"
```

**Expected Output:**
```
[File created using pytest style]
```

**Verification:**
```bash
/learning
```
- [ ] test_framework preference learned (pytest)
- [ ] Confidence bar shows learning progress

---

### 5.2 Error Pattern Learning

**Setup:**
```bash
# Create file with import error
echo "import nonexistent_module" > test_error.py
python test_error.py  # Will fail
```

**Command:**
```bash
codey2 "fix the import error in test_error.py"
```

**Expected Output:**
```
[Identifies ModuleNotFoundError]
[Suggests: pip install or fix import]
```

**Verification:**
- [ ] Error recorded in database
- [ ] Fix suggestion provided
- [ ] Same error next time → faster suggestion

---

### 5.3 Strategy Effectiveness

**Setup:**
```bash
# Create file that will fail to write
mkdir readonly_dir
chmod 444 readonly_dir
```

**Command:**
```bash
codey2 "write a file to readonly_dir/test.txt"
```

**Expected Output:**
```
[Write fails with permission error]
[Strategy: use_patch or create_parent_dirs attempted]
```

**Verification:**
```bash
/learning
```
- [ ] Strategy attempt recorded
- [ ] Success/failure tracked
- [ ] Strategy stats updated

---

### 5.4 Explicit Correction

**Command (in REPL):**
```
I prefer unittest over pytest for testing
```

**Expected Output:**
```
✓ Noted preference: test_framework = unittest
```

**Verification:**
```bash
/learning
```
- [ ] Preference updated
- [ ] Confidence increased

---

## 6. Fine-tuning Workflow Tests

### 6.1 Dataset Quality Filtering

**Command:**
```bash
codey2 --finetune --ft-quality 0.9 --ft-days 7
```

**Expected Output:**
```
Curating examples from last 7 days (min_quality=0.9)...
Curated X examples (high quality only)
```

**Verification:**
- [ ] Fewer examples than default (0.7 quality)
- [ ] Higher quality threshold applied

---

### 6.2 Dataset Content Validation

**Command:**
```bash
cat ~/Downloads/codey-finetune/codey-finetune-1.5b.jsonl | head -1 | python -m json.tool
```

**Expected Output:**
```json
{
    "conversations": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ],
    "metadata": {
        "source": "codey-v2",
        "quality": 0.85,
        ...
    }
}
```

**Verification:**
- [ ] Valid JSON
- [ ] ShareGPT format
- [ ] Quality scores included

---

### 6.3 Notebook Validation

**Command:**
```bash
cat ~/Downloads/codey-finetune/codey-finetune-qwen-coder-1.5b.ipynb | python -m json.tool | head -20
```

**Expected Output:**
```json
{
    "cells": [...],
    "metadata": {...},
    "nbformat": 4
}
```

**Verification:**
- [ ] Valid Jupyter notebook format
- [ ] Contains Unsloth setup cells
- [ ] Contains training cells

---

### 6.4 LoRA Adapter Import (Mock)

**Command:**
```bash
codey2 --import-lora /nonexistent/adapter --lora-model primary
```

**Expected Output:**
```
Importing LoRA adapter from /nonexistent/adapter...
Import failed: Adapter directory not found: /nonexistent/adapter
```

**Verification:**
- [ ] Validation works
- [ ] Clear error message

---

## 7. Hybrid Backend Tests

### 7.1 Backend Info

**Command (Python):**
```python
from core.inference_v2 import get_backend_info
import json
print(json.dumps(get_backend_info(), indent=2))
```

**Expected Output (Termux/Android):**
```json
{
    "type": "unix_socket",
    "method": "llama-server + Unix domain socket HTTP",
    "overhead_ms": "~200-300ms per call",
    "backends_available": ["direct", "unix_socket"]
}
```

**Or (if Unix socket unavailable):**
```json
{
    "type": "http",
    "method": "llama-server subprocess + HTTP API",
    "overhead_ms": "~500ms per call",
    "note": "Hybrid backend unavailable, using HTTP fallback"
}
```

**Verification:**
- [ ] Backend type identified
- [ ] Overhead documented
- [ ] Available backends listed

---

### 7.2 Latency Comparison

**Command:**
```bash
# Time 5 inference calls
time for i in {1..5}; do
    codey2 "What is the capital of France?" > /dev/null
done
```

**Expected Output:**
```
real    0mXX.XXXs  # Varies by backend
```

**Verification:**
- [ ] Direct binding: ~2-3 seconds total (5 × 500ms including load)
- [ ] Unix socket: ~3-4 seconds total
- [ ] TCP HTTP: ~5-6 seconds total

---

### 7.3 Backend Fallback

**Setup:**
```python
# Simulate direct binding failure
import core.inference_hybrid as h
h._hybrid_backend = None  # Reset
```

**Command:**
```python
from core.inference_hybrid import HybridInferenceBackend
hybrid = HybridInferenceBackend()
result = hybrid.initialize()
print(f"Selected backend: {result}")
```

**Expected Output:**
```
⚠  Direct binding unavailable: Unsupported platform
ℹ  Hybrid backend: Unix socket available (secondary)
Selected backend: unix_socket
```

**Verification:**
- [ ] Direct binding attempted
- [ ] Graceful fallback to Unix socket or TCP
- [ ] No crash on failure

---

## 8. Memory & Context Tests

### 8.1 Working Memory

**Command (in REPL):**
```
/load *.py
/context
```

**Expected Output:**
```
Files in memory (turn 3):
  📄 hello.py (150 tokens, last used 0 turns ago)
  📄 test_style.py (300 tokens, last used 1 turns ago)
```

**Verification:**
- [ ] Files loaded
- [ ] Token counts shown
- [ ] Last used turn tracked

---

### 8.2 Project Memory

**Command:**
```bash
codey2 "what is this project about?"
```

**Expected Output:**
```
[Response includes CODEY.md content]
```

**Verification:**
- [ ] CODEY.md loaded automatically
- [ ] Project context used in response

---

### 8.3 Context Window Budget

**Setup:**
```bash
# Create large file
python -c "print('x' * 10000)" > large_file.py
```

**Command:**
```bash
codey2 "/read large_file.py"
```

**Expected Output:**
```
✓ Loaded: large_file.py (10000 chars)
[Truncated to fit context budget]
```

**Verification:**
- [ ] File loaded
- [ ] Truncated if exceeds 4000 token budget
- [ ] No context overflow

---

### 8.4 Episodic Memory Query

**Command (in REPL):**
```
What files did I modify yesterday?
```

**Expected Output:**
```
[Lists files from episodic log]
```

**Verification:**
- [ ] Episodic log queried
- [ ] Accurate history returned

---

## 9. Error Handling & Recovery Tests

### 9.1 Hallucination Detection

**Command:**
```bash
codey2 "create a file called test_hallucination.py"
# But don't let it actually create the file (interrupt or decline)
```

**Expected Model Response (without tool call):**
```
I have created test_hallucination.py with...
```

**Expected System Behavior:**
```
[Hallucination detected: claims file created without tool call]
[Response flagged/corrected]
```

**Verification:**
- [ ] Hallucination detected
- [ ] User warned or response corrected

---

### 9.2 Orchestration Filter (Q&A)

**Command:**
```bash
codey2 "How do I create a Flask app?"
```

**Expected Output:**
```
[Direct answer, NO orchestration plan]
```

**Verification:**
- [ ] No multi-step plan triggered
- [ ] Conversational query recognized

---

### 9.3 Orchestration Trigger (Complex Task)

**Command:**
```bash
codey2 "Create a Flask app with user authentication, database models, API endpoints, and comprehensive tests"
```

**Expected Output:**
```
Planning subtasks...
  1. Set up project structure
  2. Create database models
  3. Implement authentication
  4. Create API endpoints
  5. Write tests
  Execute this plan? [Y/n]:
```

**Verification:**
- [ ] Orchestration triggered
- [ ] Multi-step plan generated
- [ ] User confirmation requested

---

### 9.4 Strategy Recovery

**Setup:**
```bash
# Create file with syntax error
echo "def broken(" > syntax_error.py
```

**Command:**
```bash
codey2 "fix syntax_error.py"
```

**Expected Output:**
```
[Identifies SyntaxError]
[Strategy: fix_syntax applied]
[Patched file]
```

**Verification:**
- [ ] Error type identified
- [ ] Appropriate strategy selected
- [ ] Fix applied

---

## 10. Edge Cases & Stress Tests

### 10.1 Empty Prompt

**Command:**
```bash
codey2 ""
```

**Expected Output:**
```
[Handles gracefully, no crash]
```

**Verification:**
- [ ] No crash
- [ ] Graceful error or prompt for input

---

### 10.2 Very Long Prompt

**Command:**
```bash
codey2 "$(python -c 'print("x" * 100000)')"
```

**Expected Output:**
```
[Handles or truncates gracefully]
```

**Verification:**
- [ ] No crash
- [ ] Context window managed

---

### 10.3 Rapid Fire Commands

**Command:**
```bash
for i in {1..10}; do
    codey2 "What is $i + $i?" &
done
wait
```

**Expected Output:**
```
[Handles concurrent requests or queues them]
```

**Verification:**
- [ ] No daemon crash
- [ ] Requests handled (queued or processed)

---

### 10.4 Model Hot-Swap Stress

**Command:**
```bash
# Alternate between simple and complex queries
for i in {1..5}; do
    codey2 "What is 1+1?"
    codey2 "Create a class with methods and documentation"
done
```

**Expected Output:**
```
[Model swaps occur with LRU cache reducing delay]
```

**Verification:**
- [ ] No crash from rapid swapping
- [ ] LRU cache reduces reload time
- [ ] Both models work correctly

---

### 10.5 Daemon Restart Recovery

**Command:**
```bash
codeyd2 stop
codeyd2 start
codey2 "continue from last task"
```

**Expected Output:**
```
[Session recovered from SQLite]
```

**Verification:**
- [ ] State persisted across restart
- [ ] Task queue recovered
- [ ] Memory restored

---

## Test Results Template

```markdown
## Test Results

**Date:** _______________  
**Tester:** _______________  
**Codey-v2 Version:** v2.4.0

### Summary

| Category | Total Tests | Passed | Failed | Notes |
|----------|-------------|--------|--------|-------|
| Basic Functionality | 3 | | | |
| CLI Commands | 5 | | | |
| File Operations | 5 | | | |
| Shell & Security | 5 | | | |
| Learning System | 5 | | | |
| Fine-tuning | 4 | | | |
| Hybrid Backend | 3 | | | |
| Memory & Context | 4 | | | |
| Error Handling | 4 | | | |
| Edge Cases | 5 | | | |
| **TOTAL** | **43** | | | |

### Failed Tests Details

| Test ID | Description | Expected | Actual | Severity |
|---------|-------------|----------|--------|----------|
| | | | | |

### Issues Found

1. 
2. 
3. 

### Recommendations

1. 
2. 
3. 
```

---

## Quick Smoke Test (5 minutes)

For a quick validation, run these 5 commands:

```bash
# 1. Basic functionality
codey2 "What is 2+2?"

# 2. File creation
codey2 "create smoke_test.py with print('hello')"

# 3. Learning status
codey2 "/learning"

# 4. Security (should be blocked)
codey2 "run: ls; cat /etc/passwd"

# 5. Backend info
python -c "from core.inference_v2 import get_backend_info; print(get_backend_info())"
```

**All should complete without errors.**

---

## Reporting Issues

When reporting test failures, include:

1. **Test ID:** (e.g., "4.2 Shell Injection Prevention")
2. **Command run:** Exact command
3. **Expected output:** From this document
4. **Actual output:** Full output
5. **Environment:**
   - Android version
   - Termux version
   - RAM available
   - Model files present

**GitHub Issues:** https://github.com/Ishabdullah/Codey-v2/issues

---

*End of Codey-v2 User-Side Test Suite v2.4.0*
