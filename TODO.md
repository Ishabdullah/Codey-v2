# Codey-v2 — TODO & Status

**Last updated:** 2026-03-29
**Current version:** v2.7.1

---

## 🔥 Multi-Peer Pipeline — Status & Gaps (v2.7.1)

### ✅ Implemented and deterministically correct

| Item | File(s) |
|------|---------|
| `return history` crash bug fixed → `return _test_result, history` | `agent.py` |
| Auto-test follow-up suppressed when `no_plan=True` (plan step — let plan handle it) | `agent.py` |
| `filter_tool_steps` extended: peer verbs (ask/use/have/call) + `_PEER_NAME_RE` keep rule | `plannd.py` |
| `COMPLEX_SIGNALS` extended with peer keyword pairs (ask claude, use gemini, etc.) | `orchestrator.py` |
| `PLAN_PROMPT` updated with PEER CLI STEPS rule | `orchestrator.py` |
| `PLANNER_PROMPT` Rule 8: preserve "ask X to Y" in plan steps | `plannd.py` |
| Peer gate scoped to solo single-step directives; multi-step falls through to plannd | `main.py` |
| `_extract_peer_output_from_history()` helper | `agent.py` |
| Multi-peer output injection: explicit refs ("implement what Gemini planned") | `agent.py` |
| Multi-peer output injection: implicit refs ("the previous design", "what was planned") | `agent.py` |
| Git step planning added to orchestrator | `orchestrator.py` |
| Shell metacharacter blocklist removed — consent model | `shell_tools.py` |
| Malformed JSON retry in agent loop | `agent.py` |
| `max_steps` raised 6→10 | `config.py` |

### 🧪 Needs testing (heuristic / model-dependent)

**Multi-step peer routing through plannd**
- Prompt: `"Use Gemini to design a feature list for budget.py. Then use Qwen to implement it."`
- Expected: plannd creates plan with "Ask gemini to X" as step 1, "Ask qwen to Y" as step 2
- Risk: 0.5B plannd may normalize "ask gemini" → "Create X" despite Rule 8
- Mitigation: `filter_tool_steps` now keeps any step containing claude/gemini/qwen as fallback

**Multi-peer output passing**
- Test: After Gemini runs step 1 (design), does Qwen step 2 receive Gemini's output?
- Requires: history not compressed between steps (unlikely for short sessions)
- Check: `summarize_result()` in peer_cli.py must write `[Peer CLI — {name}]` prefix exactly

**Solo-peer bypass still works for simple prompts**
- Test: `"Ask Claude to explain this code"` → should bypass plannd (solo peer, no follow-up)
- Test: `"Ask gemini to review fibonacci.py and show me the results"` → "show" is part of the task sentence, not a sentence-boundary transition → should still bypass plannd

**plannd Rule 8 with 0.5B local model**
- The 0.5B model may not reliably follow Rule 8. Remote planners follow it better.
- Monitor and adjust rule wording if needed.

### ❌ Won't work without further changes

**Design-only phase type (most critical gap)**
- Problem: When Gemini is asked to "design a feature list" (not write code), `_FORMAT_INSTRUCTIONS` asks for code blocks. Gemini writes prose. `_auto_apply_peer_code` finds nothing. Falls back to asking local model to interpret.
- Fix needed: Detect `_phase_type = "design_only"` when task has "design/plan/spec/feature list" without "implement/build/code". Use a `_DESIGN_INSTRUCTIONS` block (ask for prose, not code blocks).
- Also: Write the design output to `{peer_name}_design.md` so the next peer step picks it up as a project file — more robust than history injection.
- Status: **Not implemented**

**plannd 5-step cap vs complex pipelines**
- The user's example has 7+ conceptual steps (design → implement → run features × N → README → git init → git add → git commit).
- plannd caps at 5 steps; some steps get merged or dropped.
- Fix needed: Raise `PLANNER_MAX_TOKENS` + `max_steps` in PLANNER_PROMPT, or implement multi-phase planning.
- Status: **Not implemented** — workaround: split into two prompts

**Cross-session peer output persistence**
- If session is resumed, previous peer output is not in history.
- Fix: write peer design outputs to disk (design file approach above).
- Status: **Not implemented**

**End-of-turn validation (IMPLEMENTATION_REPORT Fix 3)**
- After each plan step, validate that all original requirements are met.
- Status: **Not implemented** — low priority, retry mechanism covers most cases

---

## Validation Test — Full Pipeline

Run this to validate the multi-peer pipeline:

```
Use Gemini to design a feature list for a small CLI tool
called budget.py that tracks income and expenses with
categories, shows a balance summary, and saves everything
to JSON with persistence between runs. Then use Qwen
to implement exactly what Gemini planned. Run every
feature to verify it works. Write a README.md for it.
Then initialize a git repo in codey-test if one does
not exist and commit everything with the message:
codey-v2.7.0 final validation tests.
```

**Expected plan from plannd (ideal):**
```
1. Ask Gemini to design a feature list for budget.py
2. Ask Qwen to implement exactly what Gemini planned
3. Run: python budget.py (feature verification)
4. Write README.md for budget.py
5. Run: git init && git add . && git commit -m "codey-v2.7.0 final validation tests"
```

**Known gap:** Step 1 = design-only, but current code sends `_FORMAT_INSTRUCTIONS` (code blocks). Gemini will try to return code not a spec. The `design_only` phase fix (#1 in next steps below) is needed for this to work cleanly.

---

## Next Steps (priority order)

1. **[ ] Implement `design_only` phase type** — detect "design/plan/spec" tasks, use prose instructions, write design to `{peer}_design.md`
2. **[ ] Test multi-step peer routing** with the validation prompt above
3. **[ ] Raise plannd step cap** to 7-8 for complex pipelines
4. **[ ] `_extract_peer_output_from_history` fallback** — if history was compressed, read `{peer}_design.md` as fallback
5. **[ ] Test all three backends** (local 0.5B, openrouter, unlimitedclaude) for plannd Rule 8 compliance

---

## Pre-existing TODO (unchanged)

### Tests
- [ ] `test_extract_json` — malformed JSON parsing
- [ ] `test_is_hallucination` — false claim detection
- [ ] `test_classify_breadth_need` — task complexity classification
- [ ] `test_parse_tool_call` — tool call extraction from model output
- [ ] `test_postprocess_plan` — orchestrator plan deduplication
- [ ] Integration test: full agent loop with mock inference

### CHANGELOG gaps
- [ ] Add v2.6.7 entry (Phase 7: Cleanup & Simplification)
- [ ] Add v2.6.8 entry (Phase 8: Adaptive Depth + Thermal Awareness)

### Medium Priority
- [ ] Vision model integration (Qwen2-VL-2B)
- [ ] External API tool (http_request with allowlist)
- [ ] `bandit` security scanning in `/review`
- [ ] Audit logs + anomaly detection

### Low Priority / Future
- [ ] Better intent detection beyond keyword matching
- [ ] Post-mortem debugging (pdb integration)
- [ ] NPU acceleration (blocked upstream)
- [ ] Encrypted memory/state storage
- [ ] Runtime sandboxing
- [ ] Model hash verification

---

## Completed (reference)

- [x] Recursive LM Architecture Phases 1-8 (v2.6.1–v2.6.8)
- [x] Upgrade Roadmap Phases 1-3 (Voice, Static Analysis, Git)
- [x] Three-model architecture + plannd daemon (v2.7.0)
- [x] Context compression rework (v2.7.0)
- [x] Peer CLI delegation pipeline repairs (v2.7.1)
- [x] Shell consent model (all commands, no blocklist) (v2.7.1)
- [x] Multi-peer planning architecture (v2.7.1)
