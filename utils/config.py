import os
import shutil
from pathlib import Path

CODEY_DIR = Path(os.environ.get("CODEY_DIR", Path.home() / "codey"))
MODEL_PATH = Path(os.environ.get(
    "CODEY_MODEL",
    Path.home() / "models" / "qwen2.5-coder-7b" / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
))

# Secondary model (1.5B for simple tasks) - Phase 3
SECONDARY_MODEL_PATH = Path(os.environ.get(
    "CODEY_SECONDARY_MODEL",
    Path.home() / "models" / "qwen2.5-1.5b" / "Qwen2.5-1.5B-Instruct-Q8_0.gguf"
))

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
    "n_ctx":          4096,
    "n_threads":      4,
    "n_gpu_layers":   0,
    "verbose":        False,
    "temperature":    0.2,
    "max_tokens":     1024,
    "repeat_penalty": 1.1,
    "top_p":          0.95,
    "top_k":          40,
    "batch_size":     256,
    "kv_type":        "q8_0",
    "stop": ["<|im_end|>", "<|im_start|>"],
}

AGENT_CONFIG = {
    "max_steps":      6,
    "token_budget":   1500,
    "confirm_shell":  True,
    "confirm_write":  True,
    "history_turns":  3,
}

CODE_DIR = Path(__file__).parent.parent.resolve()
WORKSPACE_ROOT = Path(os.getcwd()).resolve()

CODEY_VERSION = "1.0.0"
CODEY_NAME    = "Codey"
