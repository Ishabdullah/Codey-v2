import os
from pathlib import Path

CODEY_DIR = Path(os.environ.get("CODEY_DIR", Path.home() / "codey"))
MODEL_PATH = Path(os.environ.get(
    "CODEY_MODEL",
    Path.home() / "models" / "qwen2.5-coder-7b" / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
))

MODEL_CONFIG = {
    "n_ctx":          2048,
    "n_threads":      6,
    "n_gpu_layers":   0,
    "verbose":        False,
    "temperature":    0.2,
    "max_tokens":     512,
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

CODEY_VERSION = "0.5.0"
CODEY_NAME    = "Codey"
