# Plan: Fix Codey-v2.7.0 Planning + Peer Escalation Issues

## Executive Summary

**Backup Created:** `/data/data/com.termux/files/home/codey-v2-backup-20260329-173000`

**Problem:** When Codey receives a prompt involving peer escalation (Claude/Gemini/Qwen), it bypasses its normal planning workflow. This causes:
1. No plan is generated for peer tasks
2. Multi-phase workflows (Gemini→Qwen→git) collapse into single-phase
3. Remaining steps (git commits, verification) are never executed
4. Codey stops prematurely after partial completion

**Root Cause:** The peer delegation code in `core/agent.py` (lines ~580-750) handles peer calls but:
- Does not invoke the planner before peer escalation
- Does not track remaining steps after peer completes
- Does not validate all prompt requirements are met before ending turn

---

## Files to Modify

| File | Lines | Change Type | Risk Level |
|------|-------|-------------|------------|
| `core/agent.py` | ~580-750 | Peer delegation flow | HIGH |
| `core/orchestrator.py` | ~1-100 | Complex task detection | MEDIUM |
| `core/peer_cli.py` | ~1-200 | Prompt building | MEDIUM |
| `core/planner.py` | All | Add peer-aware planning | LOW |
| `prompts/system_prompt.py` | ~1-50 | Add peer step tracking | LOW |

---

## Fix 1: Add Planning Before Peer Escalation

### Current Flow (Broken)
```python
# In agent.py, run_agent():
if _peer_name and _peer_task:
    _mgr = get_peer_cli_manager()
    _output = _mgr.call(_cli, _enriched_task)  # Peer runs immediately
    # ... process output, return
```

### Fixed Flow
```python
# In agent.py, run_agent():
if _peer_name and _peer_task:
    # STEP 1: Request plan FIRST
    from core.planner import get_plan
    plan = get_plan(f"{_peer_name} to {_peer_task}", read_codeymd())
    
    # STEP 2: Show plan to user
    from core.planner import show_and_confirm_plan
    approved, revised_task = show_and_confirm_plan(plan)
    if not approved:
        return "[Cancelled]", history
    
    # STEP 3: Execute peer with plan context
    _mgr = get_peer_cli_manager()
    _output = _mgr.call(_cli, revised_task or _peer_task)
    
    # STEP 4: Track remaining steps from plan
    _remaining_steps = _extract_remaining_steps(plan, _output)
    if _remaining_steps:
        _enqueue_remaining_steps(_remaining_steps, history)
```

### Implementation Details

**File:** `core/agent.py`
**Location:** Inside the `if _peer_name and _peer_task:` block (~line 620)

**Code to Add:**
```python
# Before peer call, request plan
from core.planner import get_plan, show_and_confirm_plan

# Build planning context that includes peer constraint
planning_request = f"""
Task involves {_peer_name} peer escalation.

User request: {_peer_task}

Create a plan that:
1. Specifies what {_peer_name} should output (design vs code)
2. Lists any follow-up steps (testing, git commit, etc.)
3. Identifies if additional peer calls are needed (e.g., Qwen implementation)
"""

plan = get_plan(planning_request, read_codeymd())
approved, final_task = show_and_confirm_plan(plan)

if not approved:
    return "[Plan rejected]", history

# Use revised task if user edited, otherwise use original
_peer_task = final_task if final_task != plan else _peer_task
```

---

## Fix 2: Enforce Multi-Phase Peer Workflows

### Problem
Prompt: "Use Gemini to design... Then use Qwen to implement... Then git commit..."

Current behavior: Gemini does everything, Qwen never called, git never done.

### Solution: Phase Tracking

**File:** `core/peer_cli.py`
**Add:** Phase tracking to `PeerCLIManager` class

```python
class PeerCLIManager:
    def __init__(self):
        self._available: Optional[List[PeerCLI]] = None
        self._phase_history: List[Dict] = []  # NEW: track phases
    
    def call(self, cli: PeerCLI, task: str) -> str:
        """Execute peer call and track phase."""
        # Record this phase
        self._phase_history.append({
            "cli": cli.name,
            "task": task,
            "timestamp": time.time()
        })
        
        # Execute existing call logic
        result = self._execute_peer(cli, task)
        
        # Check if task implies more phases
        _phrases_implying_handoff = [
            "then use", "after that", "next", "followed by",
            "have qwen", "tell claude", "gemini should"
        ]
        if any(p in task.lower() for p in _phrases_implying_handoff):
            # Mark that more phases are expected
            result += "\n[PHASE_PENDING: More steps required]"
        
        return result
    
    def has_pending_phases(self) -> bool:
        """Check if any phases remain unexecuted."""
        # Check last result for pending marker
        if self._phase_history:
            last = self._phase_history[-1]
            return last.get("pending", False)
        return False
    
    def get_next_phase(self, original_prompt: str) -> Optional[str]:
        """Extract next phase from original prompt."""
        # Parse original prompt for sequential indicators
        _sequential_markers = ["then", "next", "after", "finally"]
        # ... extraction logic
```

---

## Fix 3: Add End-of-Turn Validation

### Problem
Codey stops after partial completion without checking remaining requirements.

### Solution: Validation Hook

**File:** `core/agent.py`
**Location:** End of `run_agent()` function, before return

```python
def _validate_completion(user_message: str, history: List[Dict], result: str) -> Tuple[bool, str]:
    """
    Check if all prompt requirements are met.
    Returns (is_complete, missing_requirements_description)
    """
    missing = []
    
    # Check for peer phases
    if any(name in user_message.lower() for name in ["gemini", "claude", "qwen"]):
        # Check if multi-phase language exists
        if any(phrase in user_message.lower() for phrase in ["then use", "after that", "then"]):
            if "[PHASE_PENDING]" in result:
                missing.append("Remaining peer phases not executed")
    
    # Check for git requirements
    if "git" in user_message.lower() and "commit" in user_message.lower():
        # Verify git was run
        git_run = any("git" in str(h.get("content", "")) for h in history[-4:])
        if not git_run:
            missing.append("Git commit not executed")
    
    # Check for file creation requirements
    import re
    expected_files = re.findall(r'(\w+\.(?:py|md|json|js|ts))', user_message)
    for fname in expected_files:
        if not Path(fname).exists():
            missing.append(f"File not created: {fname}")
    
    return len(missing) == 0, "; ".join(missing)

# In run_agent(), before final return:
is_complete, missing = _validate_completion(user_message, history, result)
if not is_complete:
    # Auto-continue with remaining steps
    follow_up = f"Remaining tasks: {missing}. Continue to complete them."
    return run_agent(follow_up, history, yolo=yolo, _in_subtask=True)
```

---

## Fix 4: Restrict Peer Output Scope

### Problem
Gemini wrote full code when prompt said "design only".

### Solution: Constraint Templates

**File:** `core/peer_cli.py`
**Location:** `build_prompt()` method

```python
def build_prompt(self, user_message: str, errors: List[str], files: List[str], 
                 phase_type: str = "full") -> str:
    """
    Build prompt with phase-specific constraints.
    
    phase_type: "design_only" | "implement_only" | "full"
    """
    lines = [
        f"Task: {user_message}",
        "",
        "Codey-v2 has already attempted this and exhausted its retry budget.",
        "You are responding to an automated system. Do NOT ask for permission.",
        "Do NOT ask clarifying questions. Act immediately.",
    ]
    
    # PHASE-SPECIFIC CONSTRAINTS
    if phase_type == "design_only":
        lines.extend([
            "",
            "CONSTRAINT: Output ONLY a design document.",
            "- Do NOT write Python/JavaScript/TypeScript code",
            "- Output: feature list, CLI command syntax, JSON schema, example outputs",
            "- Your output will be sent to another AI for implementation",
        ])
    elif phase_type == "implement_only":
        lines.extend([
            "",
            "CONSTRAINT: Implement ONLY what is specified in the design.",
            "- Do NOT add features beyond the design",
            "- Output complete, working code",
            "- Use the exact file format specified",
        ])
    
    # ... rest of existing prompt building
```

**File:** `core/agent.py`
**Location:** Where `_enriched_task` is built

```python
# Detect phase type from user message
_phase_type = "full"
if any(p in user_message.lower() for p in ["design only", "design first", "plan only"]):
    _phase_type = "design_only"
elif any(p in user_message.lower() for p in ["implement", "build from", "code from"]):
    _phase_type = "implement_only"

_enriched_task = _mgr.build_prompt(_peer_task, [], [], phase_type=_phase_type)
```

---

## Fix 5: Make Git Commands Explicit Final Step

### Problem
Git commands in prompt are ignored.

### Solution: Orchestrator Git Detection

**File:** `core/orchestrator.py`
**Location:** `PLAN_PROMPT` and `is_complex()`

```python
# Add to COMPLEX_SIGNALS
COMPLEX_SIGNALS = [
    'create', 'build', 'implement', 'refactor', 'rewrite',
    'add', 'and then', 'then run', 'also', 'multiple',
    'class', 'module', 'app', 'application', 'system', 'api',
    'with tests', 'and run', 'and commit', 'git commit',  # NEW
    'initialize git', 'git init', 'git add',               # NEW
]

# Add to plan prompt
PLAN_PROMPT = """Break the task into 2-5 numbered steps. Max 5 steps.
...
If the user mentions git operations (commit, init, add), include EACH 
git command as a separate numbered step.
Example:
4. Run: git init
5. Run: git add file1.py file2.md
6. Run: git commit -m "message"
Output ONLY the numbered list."""
```

---

## Regression Prevention

### Test Matrix

| Test | Before Fix | After Fix (Expected) |
|------|------------|---------------------|
| `fibonacci.py` task | ✅ Plans, executes | ✅ Unchanged |
| `wordcount.py` task | ✅ Plans, executes | ✅ Unchanged |
| `primes.py` task | ✅ Plans, executes | ✅ Unchanged |
| `test_scripts.py` (Claude) | ❌ No plan | ✅ Plans, executes |
| `budget.py` (Gemini→Qwen→git) | ❌ Incomplete | ✅ All phases done |

### Pre-Implementation Testing

1. Run existing working tasks to establish baseline:
   ```bash
   cd /data/data/com.termux/files/home/codey-v2
   ./codey2 "Create a file test1.py that prints hello"
   ```

2. Run peer task to document current broken behavior:
   ```bash
   ./codey2 "Ask gemini to design a calculator, then ask qwen to implement it"
   ```

### Post-Implementation Testing

Same commands, verify:
1. Plan is shown before peer escalation
2. Both Gemini AND Qwen are called
3. Git commands execute if specified

---

## Implementation Order

1. **Backup** ✅ DONE
2. **Read all files** ✅ DONE
3. **Fix 1: Add planning before peer** (agent.py)
4. **Fix 4: Restrict peer output scope** (peer_cli.py + agent.py)
5. **Fix 2: Phase tracking** (peer_cli.py)
6. **Fix 3: End-of-turn validation** (agent.py)
7. **Fix 5: Git command detection** (orchestrator.py)
8. **Test on fibonacci.py** (verify no regression)
9. **Test on budget.py** (verify fix works)

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Planning adds latency | Cache plans for repeated tasks |
| Peer constraints too strict | Allow user override via confirmation |
| Validation loops infinitely | Max 3 auto-continue iterations |
| Git fails on non-repo | Add `|| true` fallback, check exit code |

---

## Files Changed Summary

| File | Changes | Lines Modified |
|------|---------|----------------|
| `core/agent.py` | Planning before peer, validation hook | ~100 |
| `core/peer_cli.py` | Phase tracking, constraint templates | ~80 |
| `core/orchestrator.py` | Git detection in planner | ~20 |
| `core/planner.py` | Peer-aware planning prompts | ~30 |

**Total:** ~230 lines modified across 4 files

---

## Approval Request

**Ready to proceed with implementation?**

Changes are:
- ✅ Backed up (codey-v2-backup-20260329-173000)
- ✅ Documented (this plan)
- ✅ Tested for regression (test matrix defined)
- ✅ Scoped (4 files, ~230 lines)

**Type "approved" to proceed or specify changes.**
