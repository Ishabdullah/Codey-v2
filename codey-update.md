# Codey-v2 Update Plan

## Hardware Constraints (S24 Ultra, 12GB RAM)

- **Available RAM:** ~6-8GB (Android uses 3-4GB, system processes 1-2GB)
- **CPU Threads:** 4 max (phone thermal throttling at higher counts)
- **Context:** Coding is a long-running task, not burst queries
- **No cloud:** Everything must run locally

---

## Model Strategy: Two-Model Hot-Swap

### Primary Model (Current)
| Setting | Value |
|---------|-------|
| Model | `Qwen2.5-Coder-7B-Instruct` |
| Quantization | `Q4_K_M.gguf` (~4.2GB) |
| Context | `8192` tokens |
| Threads | `4` |
| Use Case | Code generation, debugging, refactoring, planning, test writing |

**Why Q4_K_M over Q5_K_M:**
- Leaves ~3-4GB headroom for KV cache and context
- At 8192 context, KV cache needs ~2GB+
- Q4_K_M has minimal quality loss for coding tasks
- Thermal sustainability > marginal quality gains

### Secondary Model (New)
| Setting | Value |
|---------|-------|
| Model | `Qwen2.5-1.5B-Instruct` |
| Quantization | `Q8_0.gguf` (~2GB) |
| Context | `4096` tokens |
| Threads | `4` |
| Use Case | File listing, simple searches, "what does this do?", quick Q&A |

---

## Routing Logic

```
User Input → Route Decision → Load Model → Execute
                │
                ├── < 50 chars + no code keywords → 1.5B
                ├── "list", "search", "what is" → 1.5B
                ├── "fix", "create", "build", "test" → 7B
                └── Multi-file tasks, planning → 7B
```

**Implementation:**
- Never load both models simultaneously (memory pressure)
- Hot-swap: unload current, load target (2-3 second delay acceptable)
- Cache last-loaded model to avoid thrashing on back-to-back requests

---

## Configuration Changes (`utils/config.py`)

```python
MODEL_CONFIG = {
    # Primary coding model
    "primary_model": "model/qwen2.5-coder-7b-instruct.Q4_K_M.gguf",
    "primary_ctx": 8192,
    
    # Secondary fast model
    "secondary_model": "model/qwen2.5-1.5b-instruct.Q8_0.gguf",
    "secondary_ctx": 4096,
    
    # Shared settings
    "n_threads": 4,
    "batch_size": 512,
    "kv_type": "f16",
    
    # Routing thresholds
    "simple_task_threshold": 50,  # chars
    "simple_keywords": ["list", "show", "what", "where", "search", "find"],
    "complex_keywords": ["create", "build", "fix", "implement", "refactor", "test"],
}

AGENT_CONFIG = {
    "max_steps": 10,
    "history_turns": 5,
    "confirm_shell": True,
    "confirm_write": True,
}
```

---

## Core Changes Required

### 1. Model Loader (`core/loader.py`)
- Add `load_secondary_model()` function
- Add `unload_model()` function (currently missing)
- Track which model is currently loaded
- Implement hot-swap logic with 2-3 second delay

### 2. Router (`core/router.py` — NEW FILE)
```python
def route_task(user_input: str) -> str:
    """Return 'primary' or 'secondary' based on task complexity."""
    if len(user_input) < 50:
        if any(kw in user_input.lower() for kw in SIMPLE_KEYWORDS):
            return 'secondary'
    if any(kw in user_input.lower() for kw in COMPLEX_KEYWORDS):
        return 'primary'
    return 'primary'  # Default to capable model
```

### 3. Inference (`core/inference.py`)
- Modify `infer()` to accept `model='primary'` parameter
- Check if requested model is loaded
- Auto-swap if different model needed
- Add `swap_model()` helper with cooldown tracking

### 4. Memory Manager (`core/memory.py`)
- Add model state to turn tracking
- Prevent swap during active multi-step tasks
- Add `model_cooldown` to avoid thrashing

---

## Thermal Management

```python
# Add to utils/config.py
THERMAL_CONFIG = {
    "max_threads": 4,
    "throttle_after_seconds": 300,  # 5 min continuous
    "cooldown_seconds": 60,         # 1 min rest
    "temperature_warning": 45,      # Celsius (if sensor available)
}
```

**Mitigation:**
- Add `--threads` override flag for user control
- Show thermal warning after 5+ min continuous inference
- Auto-reduce to 2 threads if phone gets hot (future: read thermal sensor)

---

## Performance Expectations

| Task | Model | Est. Time |
|------|-------|-----------|
| "list files in src/" | 1.5B | ~1-2 sec |
| "what does this function do?" | 1.5B | ~3-5 sec |
| "fix this bug" | 7B | ~15-30 sec |
| "create a REST API with auth" | 7B | ~60-120 sec |
| TDD loop (5 iterations) | 7B | ~5-10 min |

**Note:** 7B @ 4 threads = ~3-5 tokens/sec. Patient but capable.

---

## Download Commands

```bash
# Primary model (if not already present)
mkdir -p ~/codey-v2/model
cd ~/codey-v2/model

# Qwen2.5-Coder-7B-Instruct Q4_K_M
wget https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf

# Secondary model (new)
wget https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q8_0.gguf
```

---

## Future Optimizations (Post-Update)

1. **NPU Acceleration:** If llama.cpp adds Snapdragon NPU support, offload layers
2. **Vector Memory:** Add embeddings for "that file I edited last week" search
3. **Background Daemon:** Run as persistent service, not per-command spawn
4. **Direct llama.cpp binding:** Remove HTTP server overhead
5. **Checkpointing:** Auto-save state before self-modification

---

## Testing Checklist

- [ ] Both models download and load successfully
- [ ] Hot-swap works without crash
- [ ] Routing correctly identifies simple vs complex tasks
- [ ] 8192 context doesn't OOM at 4 threads
- [ ] Phone thermal throttling is manageable
- [ ] TDD loop completes without thermal shutdown
- [ ] Session save/load works across model swaps
