import os
import shutil
from pathlib import Path

CODEY_DIR = Path(os.environ.get("CODEY_DIR", Path.home() / "codey-v2"))
MODEL_PATH = Path(os.environ.get(
    "CODEY_MODEL",
    Path.home() / "models" / "qwen2.5-coder-7b" / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
))

# Secondary model (1.5B for simple tasks) - Phase 3
SECONDARY_MODEL_PATH = Path(os.environ.get(
    "CODEY_SECONDARY_MODEL",
    Path.home() / "models" / "qwen2.5-1.5b" / "qwen2.5-1.5b-instruct-q8_0.gguf"
))

# Dedicated embedding model — Option C (v2.6.6)
# nomic-embed-text-v1.5: 80 MB Q4, 2048 ctx, 768-dim vectors.
# Runs on port 8082, separate from the 7B generation server on 8080.
# ~50 ms/chunk, covers 92.6% of chunks; rest use BM25 keyword fallback.
EMBED_MODEL_PATH = Path(os.environ.get(
    "CODEY_EMBED_MODEL",
    Path.home() / "models" / "nomic-embed" / "nomic-embed-text-v1.5.Q4_K_M.gguf"
))
EMBED_SERVER_PORT = int(os.environ.get("CODEY_EMBED_PORT", "8082"))

# Router configuration - Phase 3
ROUTER_CONFIG = {
    "simple_max_chars": 50,         # Under this length → consider simple
    "simple_keywords": ["hello", "hi", "hey", "thanks", "thank you", "bye", "goodbye"],
    "swap_cooldown_sec": 30,        # Cooldown before swapping back to primary
    "swap_delay_sec": 3,            # Expected delay for model swap
}

# Detection of llama-server binary and library path
_HOME_LLAMA = Path.home() / "llama.cpp" / "build" / "bin"
LLAMA_SERVER_BIN = os.environ.get("CODEY_LLAMA_SERVER") or shutil.which("llama-server") or str(_HOME_LLAMA / "llama-server")
LLAMA_LIB = os.environ.get("CODEY_LLAMA_LIB") or str(_HOME_LLAMA)

MODEL_CONFIG = {
    "n_ctx":          32768,
    "n_threads":      6,
    "n_gpu_layers":   0,
    "verbose":        False,
    "temperature":    0.2,
    "max_tokens":     2048,
    "repeat_penalty": 1.1,
    "top_p":          0.95,
    "top_k":          40,
    "batch_size":     1024,
    "kv_type":        "q4_0",
    # Stop the model before it can role-play the next user turn.
    # With /v1/chat/completions, llama-server handles ChatML stop tokens
    # automatically. These extra stops catch hallucinated role-play.
    "stop": ["<|im_end|>", "<|im_start|>", "\nUser:", "\nHuman:", "\nA:"],
}

AGENT_CONFIG = {
    "max_steps":      6,
    "token_budget":   1500,
    "confirm_shell":  True,
    "confirm_write":  True,
    "history_turns":  3,
}

# Thermal management + adaptive depth — Phase 8 (v2.6.8)
THERMAL_CONFIG = {
    "enabled": True,
    "warn_after_sec": 300,       # 5 minutes - log warning
    "reduce_threads_after_sec": 600,  # 10 minutes - reduce to 2 threads
    "min_threads": 2,
    "original_threads": 6,       # Will be set from MODEL_CONFIG
    # Adaptive recursion depth thresholds
    "temp_critical": 80,         # °C — skip recursion entirely
    "temp_warn":     65,         # °C — cap recursion depth to 1
    "batt_critical":  5,         # % — skip recursion (not charging)
    "batt_low":      15,         # % — cap recursion depth to 1 (not charging)
}

# Initialize original_threads from MODEL_CONFIG
THERMAL_CONFIG["original_threads"] = MODEL_CONFIG.get("n_threads", 4)

CODE_DIR = Path(__file__).parent.parent.resolve()
WORKSPACE_ROOT = Path(os.getcwd()).resolve()

# Recursive Inference — Phase 2 (v2.6.2)
# Controls the draft → critique → refine self-improvement loop.
# Set enabled=False to revert to single-pass inference.
RECURSIVE_CONFIG = {
    "enabled":            True,
    # Max critique+refine cycles per request (1 = 1 critique + 1 refine = 3 calls total)
    # Raise for higher quality at the cost of 2x–3x inference time.
    "max_depth":          1,
    # Quality gate: skip refinement if the model rates its own output >= this × 10
    "quality_threshold":  0.7,
    # Apply recursion for file-write tasks (write_file / patch_file)
    "recursive_for_writes": True,
    # Apply recursion during task planning (orchestrator)
    "recursive_for_plans":  True,
    # Skip recursion for Q&A / conversational messages (always skipped via breadth=minimal)
    "recursive_for_qa":     False,
    # Max tokens allocated to the critique response (keeps critique calls fast)
    "critique_budget":    512,
    # Max chars of KB context injected into the refine prompt for NEED_DOCS gaps
    "retrieval_budget":   1200,
}

# Knowledge Base + Retrieval — Phase 1 (v2.6.1)
RETRIEVAL_CONFIG = {
    "enabled":            True,
    "kb_path":            str(CODEY_DIR / "knowledge"),
    "semantic_search":    True,         # prefer embeddings when index exists
    "max_chunks":         4,            # max results per retrieval query
    "budget_chars":       2400,         # max chars of retrieved content (~600 tokens)
    "embedding_model":    "all-MiniLM-L6-v2",
    "min_score":          0.0,          # minimum raw score (keyword: overlap count)
    "semantic_threshold": 0.3,          # minimum cosine similarity for semantic results
}

CODEY_VERSION = "2.6.8"
CODEY_NAME    = "Codey-v2"
