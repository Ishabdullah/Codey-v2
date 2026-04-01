# Configuration

## Daemon Config

Default location: `~/.codey-v2/config.json`

Generate with: `codeyd2 config`

```json
{
  "daemon": {
    "pid_file":    "~/.codey-v2/codey-v2.pid",
    "socket_file": "~/.codey-v2/codey-v2.sock",
    "log_file":    "~/.codey-v2/codey-v2.log",
    "log_level":   "INFO"
  },
  "tasks": {
    "max_concurrent":  1,
    "task_timeout":    1800,
    "max_retries":     3
  },
  "health": {
    "check_interval":        60,
    "max_memory_mb":         1500,
    "stuck_task_threshold":  1800
  },
  "state": {
    "db_path":                    "~/.codey-v2/state.db",
    "cleanup_old_actions_hours":  24
  }
}
```

---

## Model Config

Edit `utils/config.py` to tune inference behavior.

```python
MODEL_CONFIG = {
    "n_ctx":          32768,   # Context window
    "n_threads":      4,       # CPU threads (auto-reduced under thermal load)
    "n_gpu_layers":   0,       # GPU offload layers (0 = CPU only)
    "temperature":    0.7,
    "max_tokens":     2048,    # Max response length
    "repeat_penalty": 1.1,
    "top_p":          0.8,
    "top_k":          20,
    "batch_size":     1024,
    "kv_type":        "q4_0", # KV cache quantization
}
```

---

## Planner Config

The 0.5B model runs on port 8081 and handles both task planning and conversation summarization.

```python
PLANNER_TEMPERATURE = 0.2   # Low temperature keeps plans focused
PLANNER_MAX_TOKENS  = 256   # Enough headroom for 5 clean steps
```

The planning call has a **3-minute outer timeout** (`asyncio.wait_for`, 180 s) and a **2 min 45 s HTTP timeout** (165 s) so the HTTP call always resolves before the outer timeout fires.

---

## Context Management Config

These values live in `core/summarizer.py` and control when and how conversation history is compressed.

| Setting | Value | Meaning |
|---------|-------|---------|
| `SUMMARIZE_THRESHOLD_PCT` | 0.55 | Trigger compression when context hits 55% |
| `DROP_TARGET_PCT` | 0.40 | Drop turns until usage falls to 40% |
| `MICRO_SUMMARY_MSG_LIMIT` | 2000 | Max chars per message fed to the 0.5B summarizer |

**Pinned messages** (never dropped): anything containing `write_file`, `patch_file`, `[ERROR]`, `[PATCH_FAILED]`, `[BLOCKED]`, `[CONVERSATION SUMMARY]`, `Tool error:`, or `shell`.

---

## Thermal Management Config

```python
THERMAL_CONFIG = {
    "enabled":                  True,
    "warn_after_sec":           300,    # 5 min → log warning
    "reduce_threads_after_sec": 600,    # 10 min → drop to 2 threads
    "min_threads":              2,
    "temp_critical":            90,     # °C — skip recursion entirely
    "temp_warn":                75,     # °C — cap recursion depth to 1
    "batt_critical":            5,      # % — skip recursion if not charging
    "batt_low":                 15,     # % — cap recursion depth to 1
}
```

---

## Recursive Inference Config

```python
RECURSIVE_CONFIG = {
    "enabled":               True,
    "max_depth":             1,     # 1 = draft → critique → refine (3 calls total)
    "quality_threshold":     0.7,   # Skip refinement if self-score >= 7/10
    "recursive_for_writes":  True,
    "recursive_for_plans":   True,
    "recursive_for_qa":      False, # Never recurse on Q&A
    "critique_budget":       512,   # Max tokens for critique response
    "retrieval_budget":      1200,  # Max chars of KB context in refine prompt
}
```

---

## Retrieval Config

```python
RETRIEVAL_CONFIG = {
    "enabled":            True,
    "kb_path":            "~/codey-v2/knowledge",
    "semantic_search":    True,
    "max_chunks":         4,
    "budget_chars":       2400,    # ~600 tokens of retrieved content per call
    "semantic_threshold": 0.3,     # Minimum cosine similarity
}
```

---

## Agent Config

Key agent behavior settings in `utils/config.py`:

```python
AGENT_CONFIG = {
    "max_steps":     10,    # Max tool-call steps per task
    "confirm_shell": True,  # Prompt user before every shell command
    "yolo":          False, # Skip all confirmation prompts
}
```

---

## Environment Variable Overrides

Any model path or port can be overridden without editing `config.py`:

| Variable | Default | Notes |
|----------|---------|-------|
| `CODEY_MODEL` | `~/models/qwen2.5-coder-7b/qwen2.5-coder-7b-instruct-q4_k_m.gguf` | |
| `CODEY_EMBED_MODEL` | `~/models/nomic-embed/nomic-embed-text-v1.5.Q4_K_M.gguf` | |
| `CODEY_PLANNER_MODEL` | `~/models/qwen2.5-0.5b/qwen2.5-0.5b-instruct-q8_0.gguf` | |
| `CODEY_EMBED_PORT` | `8082` | |
| `CODEY_PLANND_PORT` | `8081` | |
| `CODEY_LLAMA_SERVER` | Auto-detected from PATH or `~/llama.cpp/build/bin/llama-server` | |
| `CODEY_7B_MMAP` | `1` (enabled) | |
| `CODEY_7B_MLOCK` | `0` (disabled) | |
| `CODEY_BACKEND` | `local` | Coder backend: `local`, `openrouter`, `unlimitedclaude` |
| `CODEY_BACKEND_P` | `local` | Planner backend (independent of coder backend) |
