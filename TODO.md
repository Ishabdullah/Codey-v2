# Codey-v2 — Remaining Work

**Last updated:** 2026-03-26
**Current version:** v2.7.0

All planned roadmap phases are complete (Recursive LM Phases 1-8, Upgrade Phases 1-3).
Items below are collected from all prior planning docs and represent potential future work.

---

## High Priority

### Tests
- [x] Create `tests/` directory with unit tests (done — 57 tests passing)
- [ ] `test_extract_json` — malformed JSON parsing
- [ ] `test_is_hallucination` — false claim detection
- [ ] `test_classify_breadth_need` — task complexity classification
- [ ] `test_get_adaptive_depth` — thermal/battery depth adjustment
- [ ] `test_parse_tool_call` — tool call extraction from model output
- [ ] `test_postprocess_plan` — orchestrator plan deduplication
- [ ] `test_clean_response` — hallucination marker stripping
- [ ] Integration test: full agent loop with mock inference

### CHANGELOG gaps
- [ ] Add v2.6.7 entry (Phase 7: Cleanup & Simplification)
- [ ] Add v2.6.8 entry (Phase 8: Adaptive Depth + Thermal Awareness)
- [ ] Mark "Voice Interface" as done in Future Considerations section

---

## Medium Priority

### Vision Model (from upgrade roadmap Phase 5)
- [ ] Download Qwen2-VL-2B (GGUF) + mmproj file
- [ ] Image detection in user messages (.png, .jpg, .webp, .pdf paths)
- [ ] Vision → text → coding pipeline (swap in vision model, describe, swap out)
- [ ] Use cases: screenshot errors, UI mockups, diagrams, handwritten notes

### External API Tool (from upgrade roadmap Phase 6)
- [ ] `http_request` agent tool (GET/POST/PUT/DELETE)
- [ ] Domain allowlist safety layer (user-configured)
- [ ] Built-in integrations: GitHub API, PyPI, doc fetching

### Security scanning
- [ ] Add `bandit` to `/review` for Python security analysis
- [ ] Audit logs + anomaly detection

---

## Low Priority / Future Considerations

### NLP & Routing (from upgrade roadmap Phase 7)
- [ ] Better intent detection beyond keyword matching
- [ ] Conversation memory compression with anchor turns
- [ ] Proactive suggestions after task completion

### Debugging Tools (from upgrade roadmap Phase 8)
- [ ] Auto post-mortem debugging (pdb integration)
- [ ] Interactive debug session (`/debug <file>`)
- [ ] Test-driven debug loop (failing test → pdb → fix → rerun)

### Infrastructure
- [ ] NPU acceleration (blocked on llama.cpp upstream)
- [ ] Encrypted memory/state storage
- [ ] Runtime sandboxing
- [ ] Model signature/hash verification
- [ ] Multi-device sync
- [ ] Plugin system for third-party tools
- [ ] GUI dashboard / web UI

---

## Completed (for reference)

### Recursive LM Architecture (Phases 1-8)
- [x] Phase 1 (v2.6.1): Knowledge Base + RAG Retrieval
- [x] Phase 2 (v2.6.2): Core Recursive Inference
- [x] Phase 3 (v2.6.3): Layered System Prompts
- [x] Phase 4 (v2.6.4): Recursive Planning + Orchestration
- [x] Phase 5 (v2.6.5): Skill Loading + External Repos
- [x] Phase 6 (v2.6.6): Dedicated Embedding Server
- [x] Phase 7 (v2.6.7): Cleanup & Simplification
- [x] Phase 8 (v2.6.8): Adaptive Depth + Thermal Awareness

### Upgrade Roadmap (Phases 1-3)
- [x] Phase 1 (v2.5.1): Voice Interface (TTS + STT + toggle)
- [x] Phase 2 (v2.5.2): Static Analysis & Code Review
- [x] Phase 3 (v2.5.5): Git Enhancements (branches, merge, smart commits)
