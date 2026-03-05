import os
import shutil
from pathlib import Path

CODEY_DIR = Path(os.environ.get("CODEY_DIR", Path.home() / "codey"))
MODEL_PATH = Path(os.environ.get(
    "CODEY_MODEL",
    Path.home() / "models" / "qwen2.5-coder-7b" / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
))

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

CODEY_VERSION = "0.9.2"
CODEY_NAME    = "Codey"
