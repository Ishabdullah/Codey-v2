# importantdoc.md — Qwen2.5-Coder-7B-Instruct Prompting Guide for Codey-v2

This document captures everything you need to know to get correct tool calls, proper instruction following, and reliable code generation from the exact model Codey-v2 runs: **Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf** via llama-server.

---

## 1. Model Identity

| Property | Value |
|---|---|
| Model family | Qwen2.5-Coder |
| Size | 7B parameters |
| Variant | Instruct (instruction-tuned, NOT base) |
| Quantization | Q4_K_M (4-bit, medium quality) |
| Context window | 32768 tokens (supports up to 128K in fp16) |
| Architecture | Transformer decoder, GQA, RoPE |
| Training focus | Code generation + instruction following |
| Released by | Alibaba Cloud (Oct 2024) |

The Instruct variant is fine-tuned with RLHF specifically for chat and tool-use tasks. It expects the **ChatML** format — raw completions (`/completion` endpoint) bypass the chat template and cause instruction-following failures.

---

## 2. ChatML Format (Required)

Qwen2.5-Coder-Instruct uses ChatML as its native conversation format. llama-server applies this automatically when you use `/v1/chat/completions`. **Never send raw text to `/completion`.**

### Wire format (what the model actually sees):
```
<|im_start|>system
{system prompt}<|im_end|>
<|im_start|>user
{user message}<|im_end|>
<|im_start|>assistant
{model response}<|im_end|>
<|im_start|>user
{next user message}<|im_end|>
<|im_start|>assistant
```

### Special tokens:
| Token | ID | Meaning |
|---|---|---|
| `<\|im_start\|>` | 151644 | Turn boundary start |
| `<\|im_end\|>` | 151645 | Turn boundary end |
| `<\|endoftext\|>` | 151643 | Document end |

### Stop sequences Codey must send:
```python
stop = ["<|im_end|>", "<|im_start|>", "<|endoftext|>"]
```
Without these, the model will continue generating the next turn itself (role-play leakage).

### Codey's current config (`utils/config.py`):
```python
"stop": ["<|im_end|>", "<|im_start|>", "\nUser:", "\nHuman:", "\nA:"]
```
✅ Correct — `<|im_end|>` and `<|im_start|>` are present. The legacy stops (`\nUser:` etc.) are harmless.

---

## 3. Sampling Parameters — Official vs. Codey

### Qwen's official defaults for Instruct models:
| Parameter | Official Default | Codey Current | Recommendation |
|---|---|---|---|
| `temperature` | 0.7 | 0.2 | Raise to 0.7 for creative/tool tasks |
| `top_p` | 0.8 | 0.95 | Lower to 0.8 |
| `top_k` | 20 | 40 | Lower to 20 |
| `repeat_penalty` | 1.05–1.1 | 1.2 | Lower to 1.1 |
| `min_p` | 0.0 | not set | Leave unset |

### Why this matters:

**temperature=0.2** makes the model overly greedy — it picks the highest-probability token almost every time. For instruction-following this sounds good but actually causes:
- Repetition loops (greedy decoding gets stuck)
- Template echoing (model copies system prompt because it's the most likely continuation)
- Poor tool call format (model chooses the "safe" path of explaining rather than formatting)

**top_k=40** combined with **top_p=0.95** keeps too many candidates alive, amplifying the temperature issue.

**repeat_penalty=1.2** is aggressive. The Qwen team ships 1.05–1.1. Higher values cause the model to avoid correct repeated tokens (like JSON keys) and degrade structure.

### Recommended fix in `utils/config.py`:
```python
MODEL_CONFIG = {
    "n_ctx": 32768,
    "n_threads": 4,
    "temperature": 0.7,    # ← was 0.2
    "top_p": 0.8,          # ← was 0.95
    "top_k": 20,           # ← was 40
    "repeat_penalty": 1.1, # ← was 1.2
    "max_tokens": 2048,
    "kv_type": "q4_0",
    "stop": ["<|im_end|>", "<|im_start|>", "\nUser:", "\nHuman:", "\nA:"],
}
```

> **Note**: For pure Q&A (is_qa path), lower temperature (0.3–0.5) produces more factual, less wandering answers. The per-call `max_tokens` override already handles QA (512 cap). Consider a separate QA temperature too.

---

## 4. System Prompt Guidelines

### Length limits:
- The 7B model has a **recency bias** — it attends most strongly to the last ~2000 tokens of context
- System prompts over ~800 tokens risk being partially ignored, especially early rules
- Codey's current system prompt: ~400 tokens (base) + injected context layers
- **Keep the base system prompt under 600 tokens**; let layered_prompt.py handle dynamic injection

### Rule placement:
- **Critical rules go LAST** in the system prompt — recency bias means later rules are followed more reliably
- Tool format (`<tool>...</tool>`) and "ACT don't explain" must be near the bottom
- Background info (capabilities list, slash commands) can go at the top

### What 7B models struggle with:
- More than ~8 distinct rules in one prompt
- Conditional logic chains ("if X then Y unless Z")
- Multi-level nested instructions
- Abstract constraints ("be helpful but not verbose and never repeat yourself but do acknowledge...")

### Codey's current system prompt structure (`prompts/system_prompt.py`):
1. Identity + capabilities (top)
2. Slash commands
3. Tool call format + tool list
4. Rules (bottom) ← ✅ correct placement

---

## 5. Tool Call Format — Custom vs. Native

### Why Codey uses `<tool>...</tool>` instead of OpenAI function calling:

Qwen2.5-Coder-7B-Instruct was trained on function calling via a special `<tool_call>` format used in Qwen-Agent. The llama.cpp HTTP server does NOT support this natively — it would require the `/v1/chat/completions` `tools` parameter which llama-server partially implements but inconsistently.

**The custom `<tool>...</tool>` format is the right choice.** It's explicitly shown in the system prompt so the model learns it from context rather than relying on native fine-tuning. This is more reliable for a quantized 7B than hoping native tool-use weights survived quantization cleanly.

### Required system prompt elements for reliable tool calls:
```
TOOL CALL FORMAT — output ONLY this block when an action is required:
<tool>
{"name": "TOOL_NAME", "args": {"key": "value"}}
</tool>

ONE tool call per response. Output ONLY the <tool> block, nothing else.
```

Both "ONLY this block" and "nothing else" are necessary — without explicit exclusivity instructions, the 7B model will narrate around the tool call.

### Known 7B tool call failure modes:

| Failure | Cause | Codey's Fix |
|---|---|---|
| Explains code instead of write_file | System prompt not explicit; low temperature safe path | "ACT don't explain" rule + hallucination retry |
| Triple-quote JSON `"""..."""` | Model outputs Python syntax inside JSON | `_fix_triple_quotes()` in `extract_json()` |
| Trailing commas in JSON | 7B models often write JS-style `{"a": 1,}` | Trailing comma strip in `extract_json()` |
| Missing closing brace | Context limit or repetition penalty cuts off | Brace completion in `extract_json()` |
| Runs commands after write_file | No explicit stop instruction after successful tool | Post-write "confirm in 1 sentence, do NOT run commands" |
| Tool call followed by explanation | Model continues past `</tool>` | `parse_tool_call()` stops at first valid `<tool>` block |

---

## 6. Prompting Pipeline (Complete Flow)

```
User message
    ↓
core/agent.py: run_agent()
    ↓
[is_qa check] — word-boundary regex on action keywords + QA phrases
    ↓ QA path                    ↓ Tool path
    |                            |
    |                    [is_complex check] → orchestrator.py (multi-subtask)
    |                            ↓
    |                    build_system_prompt(message)
    |                            ↓
    |                    prompts/layered_prompt.py: build_recursive_prompt()
    |                            ↓
    |                    Priority layers assembled:
    |                      p=0 (required): base SYSTEM_PROMPT
    |                      p=0 (required): CODEY.md
    |                      p=1: user notes (core/notes.py)
    |                      p=2: repo map (core/project.py)
    |                      p=3: RAG retrieval (core/retrieval.py)
    |                      p=3: skill patterns (core/skills.py)
    |                      p=4: loaded files (core/memory.py)
    |                            ↓
    |                    infer(messages, stream=True)
    |                            ↓
    |                    core/inference_v2.py: _infer_chat()
    |                            ↓
    |                    core/inference_hybrid.py: SSE streaming
    |                            ↓ /v1/chat/completions
    |                    llama-server (port 8080)
    |                            ↓ ChatML applied automatically
    |                    Qwen2.5-Coder-7B
    |                            ↓
    |                    parse_tool_call() → extract_json()
    |                            ↓ tool found
    |                    execute_tool() → TOOLS dict
    |                            ↓
    |                    [loop up to 10 steps]
    |
    ↓
is_qa=True: infer(stream=True, max_tokens=512)
            no tool loop, direct response
```

### Recursive inference (non-QA tasks):
```
classify_breadth_need(message)
  "minimal" → single infer()
  "standard" → Draft → Critique → (quality gate ≥7/10) → Refine
  "deep"    → Draft → Critique → Refine → Critique → Refine
```

Critique calls use `stream=False` and do NOT update `_last_was_streamed` — only the draft streaming call sets the flag.

---

## 7. Context Budget Management

Total context: 32768 tokens

| Layer | Budget |
|---|---|
| System prompt (base) | ~400 tokens |
| CODEY.md | ~300 tokens |
| User notes | ~100 tokens |
| Repo map | ~300 tokens (1200 chars) |
| RAG retrieval | ~150 tokens (600 chars) |
| Skill patterns | ~200 tokens (800 chars) |
| Loaded files | ~800 tokens (remaining after above) |
| Conversation history | variable |
| Model response reserve | 2048 tokens |
| **Total fixed overhead** | ~2300 tokens |
| **Available for conversation** | ~28420 tokens |

Summarization triggers at 55% of n_ctx (~18022 tokens used) and drops turns until usage falls to 40%. The `/summarize` command forces early summarization.

---

## 8. Skills System

Skills are markdown files cloned from external repos into `knowledge/skills/`. They contain prompt patterns, templates, and examples.

### How skills get injected:
1. `core/skills.py: load_relevant_skills(user_message)` is called during system prompt assembly
2. It calls `retrieve("skill template pattern: {user_message}")` to bias toward skill content
3. Returns a `## Relevant Skills\n...` block (budget: 800 chars)
4. Injected at priority=3 in LayeredPrompt (same as RAG, evicted before loaded files if tight)

### Setup:
```bash
bash tools/setup_skills.sh          # clone skill repos
codeyd2 start                       # start embed server
python3 -c "from tools.kb_semantic import build_semantic_index; build_semantic_index()"
```

### How to make the model aware of skills:
The model does NOT have native knowledge of what skills exist. Skills are injected as reference material. For the model to "know its skills," the relevant skill content must appear in the system prompt for that specific query. The `/learning` command in `main.py` shows what the model has loaded.

---

## 9. Known Failure Modes and Mitigations

### 9.1 Role-play / system prompt echo
**Symptom**: Model outputs `from core.learning import get_learning_manager` or `## User Notes` mid-response.
**Cause**: Model treats its own context as continuation target (recency + greedy decoding).
**Mitigations**:
- `_LEAK_STOP_SEQUENCES` in `agent.py` — sent as extra stop tokens to llama-server
- `HALLUCINATION_MARKERS` in `agent.py` — post-processed out of response
- Section headers added to stop list: `\n## Loaded Files`, `\nfrom core.`, etc.

### 9.2 Babbling / repetition loops
**Symptom**: Model generates "the the the the" or repeats the same sentence forever.
**Cause**: Greedy decoding (low temperature) gets trapped in high-probability cycles.
**Mitigations**:
- `repeat_penalty=1.2` (reduce to 1.1 per recommendation above)
- Streaming circuit breaker in `inference_hybrid.py` — breaks after 2 repeated ~60-char phrases
- QA token cap: 512 tokens

### 9.3 Tool call refusal ("let me explain how...")
**Symptom**: Model describes what code to write instead of emitting `<tool>`.
**Cause**: Temperature too low makes explaining the "safe" high-probability path; system prompt rules not emphatic enough.
**Mitigations**:
- "ACT don't explain" rule in system prompt with explicit trigger words (create, write, make, build)
- `is_hallucination()` detects code blocks (` ``` `) without a write_file call → forces retry with explicit write_file hint
- Raising temperature to 0.7 makes tool call format more likely to be sampled

### 9.4 Malformed JSON in tool calls
**Symptom**: `extract_json()` fails to parse tool call.
**Cause**: 7B models inconsistently apply JSON rules (Python habits: trailing commas, triple quotes, literal newlines).
**Mitigations**:
- `extract_json()` applies 3 sequential fixers: trailing comma strip, triple-quote decode, literal newline escape
- If all fixers fail, tool call is skipped and model gets another chance

### 9.5 Post-write command explosion
**Symptom**: After `write_file`, model immediately calls `shell` with `python3 -c "..."`.
**Cause**: Model predicts "test it" is the natural next step.
**Mitigation**: After write_file (without explicit run/test/execute intent in user message), inject: "File created. Confirm in 1 sentence. Do NOT run any commands."

### 9.6 Second message taking long (was triggering recursive inference)
**Symptom**: Simple "hi" or follow-up question goes through draft→critique→refine.
**Cause**: `_has_action` used substring matching — "have", "use" matched normal words.
**Mitigation**: `is_qa` and `_has_action` both use word-boundary regex (`\b...\b`). Broad action words removed.

---

## 10. Codey Config — Current State vs. Recommendations

### `utils/config.py` — key settings:

```python
# Current (as of v2.6.8):
MODEL_CONFIG = {
    "n_ctx": 32768,        # ✅ Full context (model supports up to 128K)
    "n_threads": 4,        # ✅ Correct for S24 Ultra thermal profile
    "temperature": 0.2,    # ⚠️  Too low — raises tool-call refusal risk
    "top_p": 0.95,         # ⚠️  Too high for Qwen — use 0.8
    "top_k": 40,           # ⚠️  Too high — use 20
    "repeat_penalty": 1.2, # ⚠️  Slightly aggressive — use 1.1
    "max_tokens": 2048,    # ✅ Appropriate for code tasks
    "kv_type": "q4_0",     # ✅ KV cache quantization saves ~40% RAM
}

AGENT_CONFIG = {
    "max_steps": 6,        # ✅ Reasonable ReAct loop limit
    "history_turns": 10,   # ✅ Keep last 10 turns
    "confirm_shell": True, # ✅ Safety default
    "confirm_write": True, # ✅ Safety default
}

RECURSIVE_CONFIG = {
    "enabled": True,       # ✅
    "max_depth": 1,        # ✅ Draft→Critique→Refine (depth 1 = 1 refine pass)
    "quality_threshold": 0.7,
    "critique_budget": 512,
    "retrieval_budget": 1200,
}

THERMAL_CONFIG = {
    "enabled": True,
    "temp_critical": 90,   # ✅ Skip recursion above 90°C (Snapdragon tuned)
    "temp_warn": 75,       # ✅ Cap depth at 1 above 75°C (Snapdragon tuned)
    "batt_critical": 5,
    "batt_low": 15,
}
```

---

## 11. Quick Reference — Prompting Checklist

When modifying Codey's prompting pipeline, verify:

- [ ] Using `/v1/chat/completions` (not `/completion`) — ChatML applied automatically
- [ ] Stop sequences include `<|im_end|>` and `<|im_start|>`
- [ ] System prompt base is under 600 tokens
- [ ] Critical rules (tool format, ACT rule) are at the BOTTOM of the system prompt
- [ ] Tool format says "ONLY this block, nothing else" (exclusivity language)
- [ ] `is_qa` uses word-boundary regex on action keywords
- [ ] `_has_action` does NOT match common words like "have", "use", "ask", "call"
- [ ] Post-write injection disables further tool calls when no run/test intent
- [ ] `_last_was_streamed` only set True by streaming calls, reset at start of each turn
- [ ] `extract_json()` handles trailing commas, triple-quotes, literal newlines
- [ ] Leak stop sequences cover all section headers injected by layered_prompt.py

---

## 12. References

- Qwen2.5-Coder model card: https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct
- Qwen2.5 technical report: https://arxiv.org/abs/2409.12186
- llama.cpp server docs: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- ChatML format: https://huggingface.co/docs/transformers/chat_templating
- Codey-v2 architecture: `CLAUDE.md` (this repo)
