#!/usr/bin/env python3
"""
Model loader for Codey-v2 - Termux/Android compatible.

Uses llama-server binary via subprocess instead of llama-cpp-python bindings
(since llama-cpp-python doesn't support Android platform).

Single-model architecture: always loads the primary 7B model.
"""

import subprocess
import time
import socket
import urllib.request
import urllib.error
import json
import os
import signal
from typing import Optional
from pathlib import Path

from utils.logger import info, warning, error, success
from utils.config import MODEL_PATH, MODEL_CONFIG, LLAMA_SERVER_BIN

# llama-server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080  # Default llama-server port


class LlamaServer:
    """
    Manages llama-server subprocess and HTTP API communication.

    Starts llama-server as a background process and communicates
    via HTTP API for inference.
    """

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.process: Optional[subprocess.Popen] = None
        self.port = SERVER_PORT
        self._started = False

    def start(self) -> bool:
        """Start llama-server subprocess."""
        try:
            if self.process and self.process.poll() is None:
                # Already running
                return True

            # Check if llama-server is already running on port 8080 (e.g., from daemon)
            if self._is_port_in_use():
                info(f"llama-server already running on port {self.port}, using existing server")
                self._started = True
                return True

            info(f"Starting llama-server...")

            # Build command
            cmd = [
                str(LLAMA_SERVER_BIN),
                "-m", str(self.model_path),
                "--host", SERVER_HOST,
                "--port", str(self.port),
                "-c", str(MODEL_CONFIG["n_ctx"]),
                "-t", str(MODEL_CONFIG["n_threads"]),
                "--temp", str(MODEL_CONFIG["temperature"]),
                "--top-p", str(MODEL_CONFIG["top_p"]),
                "--top-k", str(MODEL_CONFIG["top_k"]),
                "--repeat-penalty", str(MODEL_CONFIG["repeat_penalty"]),
                "--n-predict", str(MODEL_CONFIG["max_tokens"]),
                "--flash-attn", "on",  # fused attention kernel, faster prefill
                "--embedding",       # enable /v1/embeddings endpoint for hybrid KB search
                "--pooling", "mean", # mean pooling → single vector per input (OAI-compatible)
            ]

            # Add stop tokens (using --reverse-prompt)
            for stop in MODEL_CONFIG.get("stop", []):
                cmd.extend(["--reverse-prompt", stop])

            # ── mmap / mlock settings for the 7B model (Change 2) ──────────
            # Pass --mmap / --no-mmap explicitly in both directions so the flag
            # is visible in ps output and not left to llama.cpp's default.
            # --no-mlock does NOT exist in this llama.cpp build; omitting --mlock
            # is sufficient to keep mlock disabled (the llama.cpp default).
            try:
                from utils.config import QWEN_7B_MMAP, QWEN_7B_MLOCK
                if QWEN_7B_MMAP:
                    cmd.append("--mmap")
                else:
                    cmd.append("--no-mmap")
                if QWEN_7B_MLOCK:
                    cmd.append("--mlock")
                info(
                    f"7B model: mmap={'enabled' if QWEN_7B_MMAP else 'disabled'}, "
                    f"mlock={'enabled' if QWEN_7B_MLOCK else 'disabled'}"
                )
            except ImportError:
                pass  # Config not available — use llama.cpp defaults (mmap on, mlock off)

            # Start process - redirect output to log file to avoid pipe buffer issues
            log_file = Path.home() / ".codey-v2" / "llama-server.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)

            with open(log_file, "w") as f:
                f.write(f"Starting llama-server: {' '.join(cmd)}\n")
                f.flush()

            # Open log file for appending stdout/stderr
            log_fd = open(log_file, "a")

            self.process = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )

            info(f"llama-server PID: {self.process.pid}, logging to {log_file}")

            # Wait for server to be ready (up to 60 seconds for large models)
            for i in range(120):  # 120 * 0.5s = 60s timeout
                time.sleep(0.5)

                # Check if process died
                if self.process.poll() is not None:
                    error(f"llama-server process died (exit code {self.process.poll()})")
                    # Read log for error
                    try:
                        with open(log_file, "r") as f:
                            logs = f.read()
                        error(f"Server log: {logs[-1000:]}")
                    except:
                        pass
                    return False

                if self._check_health():
                    # Give server a moment to fully initialize all endpoints
                    time.sleep(0.5)
                    self._started = True
                    success(f"llama-server started on port {self.port}")
                    return True

            error(f"Timeout waiting for llama-server to start")
            self.stop()
            return False

        except Exception as e:
            error(f"Failed to start llama-server: {e}")
            import traceback
            error(traceback.format_exc())
            return False

    def stop(self):
        if self.process:
            try:
                import signal as _signal
                if os.name != "nt":
                    try:
                        os.killpg(os.getpgid(self.process.pid), _signal.SIGTERM)
                    except ProcessLookupError:
                        self.process.terminate()
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        try:
                            os.killpg(os.getpgid(self.process.pid), _signal.SIGKILL)
                        except Exception:
                            self.process.kill()
                    else:
                        self.process.kill()
            except Exception as e:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                self.process = None
                self._started = False

    def _check_health(self) -> bool:
        """Check if server is responding."""
        try:
            url = f"http://{SERVER_HOST}:{self.port}/health"
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status == 200
        except:
            return False

    def _is_port_in_use(self) -> bool:
        """Check if port 8080 is already in use by another llama-server instance."""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((SERVER_HOST, self.port))
            sock.close()
            # If port is open, check if it's actually llama-server responding
            if result == 0:
                try:
                    url = f"http://{SERVER_HOST}:{self.port}/health"
                    with urllib.request.urlopen(url, timeout=2) as response:
                        return response.status == 200
                except:
                    pass
            return result == 0
        except Exception:
            return False

    def infer(self, prompt: str, max_tokens: int = None,
              stop: list = None) -> Optional[str]:
        """
        Run inference via HTTP API.

        Args:
            prompt:     Formatted prompt string.
            max_tokens: Override max output tokens.
            stop:       Extra stop sequences to merge with MODEL_CONFIG["stop"].
                        Callers should pass the combined list so extra_stop tokens
                        (e.g. "</tool>") are honoured by the server.
        """
        if not self._started:
            error("llama-server not running")
            return None

        # Merge caller-supplied stop list with configured defaults
        base_stop = list(MODEL_CONFIG.get("stop", []))
        if stop:
            for s in stop:
                if s not in base_stop:
                    base_stop.append(s)

        # Retry logic for transient errors
        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                url = f"http://{SERVER_HOST}:{self.port}/completion"
                data = {
                    "prompt": prompt,
                    "n_predict": max_tokens or MODEL_CONFIG["max_tokens"],
                    "temperature": MODEL_CONFIG["temperature"],
                    "top_p": MODEL_CONFIG["top_p"],
                    "top_k": MODEL_CONFIG["top_k"],
                    "repeat_penalty": MODEL_CONFIG["repeat_penalty"],
                    "stop": base_stop,
                    "stream": False,
                }

                req = urllib.request.Request(
                    url,
                    data=json.dumps(data).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )

                with urllib.request.urlopen(req, timeout=300) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    return result.get("content", "").strip()

            except urllib.error.HTTPError as e:
                if e.code == 503 and attempt < max_retries - 1:
                    warning(f"Server busy (503), retrying ({attempt + 1}/{max_retries})...")
                    time.sleep(1.0)
                    last_error = e
                    continue
                error(f"HTTP error during inference: {e}")
                return None
            except urllib.error.URLError as e:
                error(f"HTTP error during inference: {e}")
                return None
            except json.JSONDecodeError as e:
                error(f"JSON decode error: {e}")
                return None
            except Exception as e:
                error(f"Inference error: {e}")
                return None

        error(f"All retries failed: {last_error}")
        return None

    def is_running(self) -> bool:
        """Check if server process is running."""
        if self.process is not None:
            return self.process.poll() is None
        # If no process but _started is True, check if port is responding
        if self._started:
            return self._check_health()
        return False


class ModelLoader:
    """
    Manages model loading via llama-server.

    Single-model: always loads the primary 7B Qwen2.5-Coder model.
    """

    def __init__(self):
        self._loaded: bool = False
        self._server: Optional[LlamaServer] = None
        self._loaded_at: float = 0
        self._load_failures: int = 0

    def load_primary(self) -> bool:
        """Load the primary (7B) model."""
        try:
            info(f"Loading model: {MODEL_PATH.name}")

            # Check if model file exists
            if not MODEL_PATH.exists():
                error(f"Model file not found: {MODEL_PATH}")
                self._load_failures += 1
                return False

            # Check if llama-server binary exists
            llama_bin = Path(LLAMA_SERVER_BIN)
            if not llama_bin.exists():
                error(f"llama-server not found: {LLAMA_SERVER_BIN}")
                self._load_failures += 1
                return False

            # Start server
            self._server = LlamaServer(MODEL_PATH)
            if not self._server.start():
                self._load_failures += 1
                return False

            self._loaded = True
            self._loaded_at = time.time()
            success(f"Loaded model ({MODEL_PATH.name})")
            return True

        except Exception as e:
            error(f"Failed to load model: {e}")
            self._load_failures += 1
            return False

    def unload(self):
        """Unload (stop) the current model server."""
        if self._server:
            info("Stopping model server...")
            self._server.stop()
            self._server = None
            self._loaded = False

    def ensure_model(self, model_type: str = "primary") -> bool:
        """Ensure the model is loaded and running."""
        if self._loaded and self._server and self._server.is_running():
            return True
        return self.load_primary()

    def get_loaded_model(self) -> Optional[str]:
        """Get the currently loaded model type."""
        return "primary" if self._loaded else None

    def is_loaded(self, model_type: str = None) -> bool:
        """Check if the model is loaded."""
        return self._loaded

    def get_model_instance(self) -> Optional[LlamaServer]:
        """Get the llama-server instance."""
        return self._server

    def get_load_failures(self) -> int:
        """Get count of consecutive load failures."""
        return self._load_failures

    def reset_failures(self):
        """Reset failure count (call after successful load)."""
        self._load_failures = 0

    def get_status(self) -> dict:
        """Get loader status."""
        return {
            "loaded_model": "primary" if self._loaded else None,
            "loaded_at": self._loaded_at,
            "uptime_seconds": time.time() - self._loaded_at if self._loaded_at else 0,
            "load_failures": self._load_failures,
            "server_running": self._server.is_running() if self._server else False,
        }


# Global loader instance
_loader: Optional[ModelLoader] = None


def get_loader() -> ModelLoader:
    """Get the global loader instance."""
    global _loader
    if _loader is None:
        _loader = ModelLoader()
    return _loader


def reset_loader():
    """Reset the global loader (for testing)."""
    global _loader
    if _loader:
        _loader.unload()
        _loader = None
