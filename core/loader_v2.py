#!/usr/bin/env python3
"""
Model loader for Codey-v2 - Termux/Android compatible.

Uses llama-server binary via subprocess instead of llama-cpp-python bindings
(since llama-cpp-python doesn't support Android platform).

Features:
- Primary model (7B) for complex tasks
- Secondary model (1.5B) for simple tasks
- HTTP API communication with llama-server
- Model hot-swap with cooldown
"""

import subprocess
import time
import socket
import urllib.request
import urllib.error
import json
import os
import signal
from typing import Optional, Literal
from pathlib import Path

from utils.logger import info, warning, error, success
from utils.config import MODEL_PATH, SECONDARY_MODEL_PATH, MODEL_CONFIG, ROUTER_CONFIG, LLAMA_SERVER_BIN

ModelType = Literal["primary", "secondary"]

# llama-server configuration
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8080  # Default llama-server port


class LlamaServer:
    """
    Manages llama-server subprocess and HTTP API communication.
    
    Starts llama-server as a background process and communicates
    via HTTP API for inference.
    """
    
    def __init__(self, model_path: Path, model_type: ModelType):
        self.model_path = model_path
        self.model_type = model_type
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

            info(f"Starting llama-server for {self.model_type} model...")
            
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
                    success(f"llama-server started for {self.model_type} model on port {self.port}")
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
    Manages model loading and hot-swapping via llama-server.

    Supports:
    - Load primary (7B) or secondary (1.5B) model
    - Unload current model
    - Hot-swap with cooldown
    - Track loaded model state
    - LRU cache for quick model restart (SIGSTOP instead of kill)
    """

    def __init__(self):
        self._loaded_model: Optional[ModelType] = None
        self._server: Optional[LlamaServer] = None
        self._loaded_at: float = 0
        self._load_failures: int = 0
        # LRU cache: keep stopped servers for quick restart
        self._stopped_servers: dict[ModelType, LlamaServer] = {}

    def load_primary(self) -> bool:
        """Load the primary (7B) model."""
        return self._load_model("primary", MODEL_PATH)

    def load_secondary(self) -> bool:
        """Load the secondary (1.5B) model."""
        return self._load_model("secondary", SECONDARY_MODEL_PATH)

    def _load_model(self, model_type: ModelType, model_path: Path) -> bool:
        """Internal method to load a model."""
        try:
            info(f"Loading {model_type} model: {model_path.name}")

            # Check if model file exists
            if not model_path.exists():
                error(f"Model file not found: {model_path}")
                self._load_failures += 1
                return False

            # Check if llama-server binary exists
            llama_bin = Path(LLAMA_SERVER_BIN)
            if not llama_bin.exists():
                error(f"llama-server not found: {LLAMA_SERVER_BIN}")
                self._load_failures += 1
                return False

            # Check if we have a cached server for this model type
            if model_type in self._stopped_servers:
                info(f"Resuming cached {model_type} model server...")
                cached_server = self._stopped_servers[model_type]
                # Resume the stopped process
                try:
                    import signal
                    os.killpg(os.getpgid(cached_server.process.pid), signal.SIGCONT)
                    time.sleep(0.5)  # Give it a moment to resume
                    if cached_server._check_health():
                        self._server = cached_server
                        self._loaded_model = model_type
                        self._loaded_at = time.time()
                        del self._stopped_servers[model_type]
                        success(f"Resumed {model_type} model from cache")
                        return True
                except Exception as e:
                    warning(f"Failed to resume cached server: {e}")
                    # Fall through to fresh start

            # Unload current model if different
            if self._loaded_model != model_type:
                self.unload()

            # Start new server
            self._server = LlamaServer(model_path, model_type)
            if not self._server.start():
                self._load_failures += 1
                return False

            self._loaded_model = model_type
            self._loaded_at = time.time()

            success(f"Loaded {model_type} model ({model_path.name})")
            return True

        except Exception as e:
            error(f"Failed to load {model_type} model: {e}")
            self._load_failures += 1
            return False

    def unload(self):
        """
        Unload the current model.
        
        Instead of killing the process, uses SIGSTOP to pause it.
        This allows quick restart without full reload delay.
        """
        if self._server:
            info(f"Pausing {self._loaded_model} model server (keeping in cache)...")
            try:
                import signal
                # Pause the process instead of killing it
                if self._server.process:
                    os.killpg(os.getpgid(self._server.process.pid), signal.SIGSTOP)
                # Store in cache for quick restart
                self._stopped_servers[self._loaded_model] = self._server
                success(f"{self._loaded_model} model paused and cached")
            except Exception as e:
                warning(f"Error pausing server (falling back to stop): {e}")
                self._server.stop()
            finally:
                self._server = None
                self._loaded_model = None

    def ensure_model(self, model_type: ModelType) -> bool:
        """Ensure a specific model is loaded."""
        if self._loaded_model == model_type and self._server and self._server.is_running():
            return True

        if model_type == "primary":
            return self.load_primary()
        else:
            return self.load_secondary()

    def get_loaded_model(self) -> Optional[ModelType]:
        """Get the currently loaded model type."""
        return self._loaded_model

    def is_loaded(self, model_type: ModelType = None) -> bool:
        """Check if a model is loaded (optionally check specific type)."""
        if model_type is None:
            return self._loaded_model is not None
        return self._loaded_model == model_type

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
            "loaded_model": self._loaded_model,
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
