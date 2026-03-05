import subprocess
import os
import time
import json

last_tps = 0.0  # tokens per second from last inference
import urllib.request
import urllib.error
import sys
from pathlib import Path
from utils.config import MODEL_CONFIG, MODEL_PATH, LLAMA_SERVER_BIN, LLAMA_LIB
from utils.logger import error, info

SERVER_URL       = "http://127.0.0.1:8081"
CHAT_URL         = f"{SERVER_URL}/v1/chat/completions"
HEALTH_URL       = f"{SERVER_URL}/health"

_server_proc = None

def _get_env():
    env = os.environ.copy()
    ld = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{LLAMA_LIB}:{ld}" if ld else LLAMA_LIB
    return env

def _server_ready(retries=90, delay=1.0) -> bool:
    for _ in range(retries):
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
                if json.loads(r.read()).get("status") == "ok":
                    return True
        except Exception:
            pass
        time.sleep(delay)
    return False

def _start_server():
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        return

    cfg = MODEL_CONFIG
    cmd = [
        LLAMA_SERVER_BIN,
        "--model",        str(MODEL_PATH),
        "--ctx-size",     str(cfg["n_ctx"]),
        "--threads",      str(cfg["n_threads"]),
        "--batch-size",   str(cfg["batch_size"]),
        "--cache-type-k", cfg["kv_type"],
        "--cache-type-v", cfg["kv_type"],
        "--port",         "8081",
        "--log-disable",
    ]

    info(f"Starting llama-server (ctx={cfg['n_ctx']}, threads={cfg['n_threads']}, batch={cfg['batch_size']}, kv={cfg['kv_type']})...")
    _server_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_get_env(),
    )

    if not _server_ready():
        error("llama-server failed to start.")
        _server_proc.kill()
        raise RuntimeError("llama-server did not become ready.")
    info("Server ready.")

def stop_server():
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
        _server_proc = None

def infer(messages: list[dict], stream: bool = True, extra_stop: list = None) -> str:
    global last_tps
    _start_server()
    cfg = MODEL_CONFIG

    stop_tokens = list(cfg["stop"]) + ["</tool>", "</write_file>", "</shell>"]
    if extra_stop:
        stop_tokens += [s for s in extra_stop if s not in stop_tokens]

    payload = json.dumps({
        "model":          "codey",
        "messages":       messages,
        "max_tokens":     cfg["max_tokens"],
        "temperature":    cfg["temperature"],
        "top_p":          cfg["top_p"],
        "top_k":          cfg["top_k"],
        "repeat_penalty": cfg["repeat_penalty"],
        "stop":           stop_tokens,
        "stream":         stream,
    }).encode("utf-8")

    req = urllib.request.Request(
        CHAT_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    response_text = ""

    import time as _time
    _t0 = _time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            if stream:
                print("\033[1;32mCodey:\033[0m ", end="", flush=True)
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        token = data["choices"][0]["delta"].get("content", "")
                        response_text += token
                        print(token, end="", flush=True)
                    except Exception:
                        continue
                print()
                import time as _time
                _elapsed = _time.time() - _t0
                if _elapsed > 0 and response_text:
                    last_tps = round(len(response_text.split()) / _elapsed, 1)
                sys.stdout.flush()
            else:
                data = json.loads(resp.read())
                response_text = data["choices"][0]["message"]["content"]
                # Capture tokens/sec from timings if available
                if "usage" in data:
                    usage = data["usage"]
                    # llama.cpp puts timing in timings field
                if "timings" in data:
                    t = data["timings"]
                    predicted = t.get("predicted_n", 0)
                    ms = t.get("predicted_ms", 0)
                    if ms > 0:
                        last_tps = round((predicted / ms) * 1000, 1)

    except urllib.error.URLError as e:
        return f"[ERROR] Server request failed: {e}"
    except Exception as e:
        return f"[ERROR] Inference failed: {e}"

    return response_text.strip()
