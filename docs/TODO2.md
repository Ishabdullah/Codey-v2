# Codey-v2 — TODO2: Deferred Items & Recommendations

**Created:** 2026-03-29
**Version:** v2.7.2

Items in this file are deferred from TODO.md. Each entry explains **why** it
was deferred, the **recommended implementation approach**, and the **risk**
if left unaddressed.

---

## 1. Pre-existing broken tests — fix or remove

**Files:** `tests/security/test_shell_injection.py`, `tests/test_finetune.py`

**Why deferred:** Both fail on import because they reference removed/renamed symbols:
- `test_shell_injection.py` imports `validate_command_structure` and
  `SHELL_METACHARACTERS` — removed in v2.7.1 (shell consent model refactor).
- `test_finetune.py` imports `SECONDARY_MODEL_PATH` from `utils/config.py` —
  symbol was renamed or removed.

**Recommendation:**
- `test_shell_injection.py`: rewrite tests around the current consent-model
  flow — test that `is_dangerous()` flags `rm -rf` and `curl`, and that
  `shell()` calls the confirm callback. Remove references to old blocklist.
- `test_finetune.py`: trace what `SECONDARY_MODEL_PATH` was supposed to be
  and either restore the export in `config.py` or update the import.

**Risk:** These tests never run, so regressions in shell safety and fine-tuning
go undetected.

---

## 2. Pre-existing hallucination and patch test failures

**Files:** `tests/test_hallucination.py` (8 failures), `tests/test_patch.py` (1 failure), `tests/test_memory.py` (1 failure)

**Why deferred:** The test assertions were written against an older version of
`is_hallucination` that accepted more phrases ("has been created",
"i wrote"). The current code's `_strong_claims` list is narrower. Similarly
`test_patch.py` checks for `[ERROR] String not found` but the current
`tool_patch_file` returns `[PATCH_FAILED]`.

**Recommendation:**
- `test_hallucination.py`: update expected phrases to match current
  `_strong_claims = ["has been created", "i created", "i've created", "has been written"]`.
  Add tests for the code-block detection path (`"```" in response`).
- `test_patch.py`: update `test_not_found` assertion to match `[PATCH_FAILED]` prefix.
- `test_memory.py::test_evict_stale_recently_used_kept`: investigate whether the
  eviction policy changed; update test to match current behavior.

**Risk:** 10 silently failing tests hide real regressions.

---

## 3. Full agent loop integration test with mock inference

**Why deferred:** Requires patching `core.inference_v2.infer` with a scripted
mock that sequences multiple responses (tool call → tool result → final answer).
Complex to set up correctly without the inference server.

**Recommended implementation:**

```python
# tests/test_agent_integration.py
from unittest.mock import patch

_RESPONSES = iter([
    # Step 1: model returns write_file tool call
    '<tool>\n{"name": "write_file", "args": {"path": "hello.py", "content": "print(1)"}}\n</tool>',
    # Step 2 (after tool result): model returns final answer
    'Created hello.py successfully.',
])

def mock_infer(messages, **kwargs):
    return next(_RESPONSES)

def test_agent_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("core.inference_v2.infer", side_effect=mock_infer):
        from core.agent import run_agent
        response, history = run_agent("Create hello.py", [], yolo=True)
    assert (tmp_path / "hello.py").exists()
    assert len(history) == 2
```

**Risk:** No true end-to-end test; tool-call routing bugs only show up in live runs.

---

## 4. Vision model integration (Qwen2-VL-2B)

**Why deferred:** Requires a separate GGUF model file (~1.5 GB) and llama-server
support for multimodal input. No clear user requirement yet.

**Recommended approach:**
- Add `VISION_MODEL_PATH` to `utils/config.py`
- Add a `vision_server.py` module (like `embed_server.py`) that starts
  llama-server on port 8083 with `--mmproj` flag
- Add `vision_describe(image_path)` to `tools/` — returns a text description
- Gate on `VISION_MODEL_PATH.exists()` — silent no-op when not installed

**Risk:** Low — primarily a capability gap, not a stability issue.

---

## 5. External API tool (`http_request` with allowlist)

**Why deferred:** Security-sensitive. An unrestricted `http_request` tool would
allow the model to exfiltrate data or make arbitrary network calls.

**Recommended approach:**
- Implement in `tools/http_tools.py` with:
  - `ALLOWED_DOMAINS` set in `utils/config.py` (default: empty = disabled)
  - Hard block on private RFC1918 addresses (127.x, 10.x, 192.168.x)
  - User confirmation prompt for each request (even in yolo mode, first time)
  - Response size cap (max 50 KB to prevent memory issues on mobile)
- Tool signature: `http_request(url, method="GET", headers=None, body=None)`
- Always log URL + response code to audit trail

**Risk:** Medium if implemented without domain allowlist. High if domain
allowlist is skipped.

---

## 6. `bandit` security scanning in `/review`

**Why deferred:** `bandit` may not be installed on Termux by default.

**Recommended approach:**
- In `core/linter.py`, add a `run_bandit(path)` function that calls
  `bandit -r {path} -f json` via subprocess with a 30s timeout.
- Surface results in `/review` output alongside existing linter output.
- Gate on `shutil.which("bandit")` — skip silently if not installed.
- Severity filter: only report HIGH and MEDIUM findings by default.

**Install:** `pip install bandit`

**Risk:** Low — missing bandit means security anti-patterns (hardcoded
secrets, shell injection, etc.) go undetected during `/review`.

---

## 7. Audit logs + anomaly detection

**Why deferred:** Significant feature requiring persistent log storage and
heuristic thresholds.

**Recommended approach:**
- Add `core/audit.py` that appends JSONL entries to `~/.codey/audit.log`:
  ```json
  {"ts": "...", "tool": "shell", "cmd": "rm -rf /tmp/x", "approved": true, "user": "u0"}
  ```
- Log every tool call with: tool name, args hash, yolo mode, user approval.
- Anomaly detection heuristics (at session end or on `/review`):
  - More than N shell calls in a single session
  - write_file to paths outside cwd
  - shell commands containing `curl | sh`, `eval`, `base64 -d`
- Surface warnings to user, not automatic blocks.

**Risk:** Low — reduces ability to audit what Codey did in a session.

---

## 8. design_only: `_is_review` + design interaction

**Why noted:** A task like `"Ask Gemini to review the current design and create
an improved design spec"` would have `_is_review = True` (because "review" is
in `_REVIEW_KW`) which suppresses `_is_design_only`. The project files would
be included (correct for the review part) but `_FORMAT_INSTRUCTIONS` would be
used (incorrect — Gemini would try to output code).

**Recommended fix:** When `_is_review` is True AND `_is_design_only` signals
are present, use `_DESIGN_INSTRUCTIONS` but still include project files. The
`_is_review` path currently hardcodes `+ _FORMAT_INSTRUCTIONS` at the end of
the `if _is_review:` block.

**Impact:** Edge case — only affects "review + design" combined tasks. Low
priority until it appears in real usage.

---

## 9. plannd Rule 8 reliability on local 0.5B

**Why noted:** The 0.5B Qwen model may rewrite "Ask gemini to design X" as
"Create a design for X" despite Rule 8. `filter_tool_steps` keeps any step
containing a peer name as a fallback, but this doesn't help if the peer name
is also rephrased away.

**Recommendation:** If Rule 8 failures are observed in local testing, add a
post-processing step in `get_plan()` that scans the original prompt for
"ask/use/have + peer_name" patterns and re-inserts them if plannd dropped them.
This would be deterministic, not model-dependent.

---

## 10. Cross-session peer output persistence (partial — design file approach)

**Status:** Partially addressed in v2.7.2. `{peer_name}_design.md` is written
to disk and `_extract_peer_output_from_history` reads it as a fallback.

**Remaining gap:** Implementation peer output (e.g. Qwen writing `budget.py`)
is not separately persisted — only the `[Peer CLI — qwen]` history entry.
If history is compressed before a third step that references Qwen's work, the
context is lost.

**Recommendation:** After each peer call, write a summary to
`{peer_name}_last_output.md` (not just for design tasks). The fallback in
`_extract_peer_output_from_history` already reads `{peer_name}_design.md` —
extend it to also check `{peer_name}_last_output.md`.
