#!/usr/bin/env python3
"""
Hybrid inference backend for Codey-v2.

Attempts direct llama-cpp-python binding first, falls back to HTTP API.
Supports Unix domain socket for reduced latency on Termux/Android.

Backend priority:
1. Direct llama-cpp-python (llama_cpp.Llama) - ~50-100ms overhead
2. Unix domain socket HTTP - ~200-300ms overhead
3. TCP localhost HTTP (fallback) - ~500ms overhead

Logs binding success/failure and per-call latency metrics.
"""

import os
import time
import socket
import urllib.request
import urllib.error
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from utils.logger import info, warning, error, success
from utils.config import MODEL_CONFIG, MODEL_PATH, SECONDARY_MODEL_PATH, LLAMA_SERVER_BIN


# =============================================================================
# Direct Binding Backend (llama-cpp-python)
# =============================================================================

class DirectBindingBackend:
    """
    Direct llama-cpp-python binding backend.
    
    Attempts to load llama-cpp-python and use Llama class directly.
    Falls back gracefully if import fails (Termux/Android compatibility).
    """
    
    def __init__(self):
        self._llama = None
        self._model_path: Optional[Path] = None
        self._available = False
        self._init_error: Optional[str] = None
        
    def initialize(self) -> bool:
        """
        Initialize direct binding.
        
        Returns:
            True if direct binding is available, False otherwise
        """
        if self._available:
            return True
            
        try:
            # Attempt import
            from llama_cpp import Llama
            
            info("Direct binding: llama-cpp-python imported successfully")
            self._available = True
            return True
            
        except ImportError as e:
            self._init_error = f"ImportError: {e}"
            warning(f"Direct binding unavailable: llama-cpp-python not installed")
            return False
            
        except RuntimeError as e:
            # Common on Termux/Android: "Unsupported platform"
            self._init_error = f"RuntimeError: {e}"
            warning(f"Direct binding unavailable: {e}")
            return False
            
        except Exception as e:
            self._init_error = f"Unexpected error: {e}"
            warning(f"Direct binding unavailable: {e}")
            return False
    
    def load_model(self, model_path: Path, n_ctx: int = 4096, n_threads: int = 4) -> bool:
        """
        Load model using direct binding.
        
        Args:
            model_path: Path to GGUF model file
            n_ctx: Context window size
            n_threads: CPU threads
            
        Returns:
            True if loaded successfully
        """
        if not self._available:
            return False
            
        try:
            from llama_cpp import Llama
            
            info(f"Direct binding: Loading model {model_path.name}...")
            start = time.time()
            
            self._llama = Llama(
                model_path=str(model_path),
                n_ctx=n_ctx,
                n_threads=n_threads,
                n_gpu_layers=0,  # CPU only on mobile
                verbose=False,
            )
            
            load_time = time.time() - start
            self._model_path = model_path
            success(f"Direct binding: Model loaded in {load_time:.1f}s")
            return True
            
        except Exception as e:
            error(f"Direct binding: Failed to load model: {e}")
            self._llama = None
            return False
    
    def unload_model(self):
        """Unload current model."""
        if self._llama:
            info("Direct binding: Unloading model")
            del self._llama
            self._llama = None
            self._model_path = None
    
    def infer(self, prompt: str, max_tokens: int = 1024, stop: List[str] = None) -> Optional[str]:
        """
        Run inference using direct binding.
        
        Args:
            prompt: Formatted prompt
            max_tokens: Maximum tokens to generate
            stop: Stop sequences
            
        Returns:
            Generated text or None on error
        """
        if not self._llama:
            return None
            
        try:
            start = time.time()
            
            output = self._llama(
                prompt,
                max_tokens=max_tokens,
                stop=stop or [],
                echo=False,
                stream=False,
            )
            
            elapsed = time.time() - start
            info(f"Direct binding: Inference in {elapsed:.2f}s")
            
            return output["choices"][0]["text"].strip()
            
        except Exception as e:
            error(f"Direct binding: Inference failed: {e}")
            return None
    
    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self._llama is not None
    
    @property
    def backend_name(self) -> str:
        """Backend identifier."""
        return "direct"


# =============================================================================
# Unix Domain Socket HTTP Backend
# =============================================================================

class UnixSocketBackend:
    """
    HTTP backend using Unix domain socket instead of TCP.
    
    Reduces latency by ~100-300ms compared to TCP localhost.
    Requires llama-server started with --socket flag.
    """
    
    def __init__(self, socket_path: str = None):
        self._socket_path = socket_path or str(Path.home() / ".codey-v2" / "llama.sock")
        self._base_url = "http+unix://" + self._socket_path
        
    def start_server(self, model_path: Path, n_ctx: int = 4096, n_threads: int = 4) -> bool:
        """
        Start llama-server with Unix socket.

        Args:
            model_path: Path to GGUF model
            n_ctx: Context window
            n_threads: CPU threads

        Returns:
            True if server started successfully
        """
        import subprocess
        import socket

        # Check if llama-server is already running on TCP port 8080
        # (e.g., started by daemon). If so, don't start a new Unix socket server.
        if self._is_tcp_server_running():
            info("Unix socket: llama-server already running on TCP 8080 (daemon mode), skipping Unix socket start")
            return False  # Trigger fallback to TCP HTTP backend

        try:
            info(f"Unix socket: Starting llama-server with socket {self._socket_path}")

            # Remove old socket if exists
            socket_file = Path(self._socket_path)
            if socket_file.exists():
                socket_file.unlink()

            # Build command with --socket flag
            cmd = [
                str(LLAMA_SERVER_BIN),
                "-m", str(model_path),
                "--socket", self._socket_path,
                "-c", str(n_ctx),
                "-t", str(n_threads),
                "--temp", str(MODEL_CONFIG["temperature"]),
                "--top-p", str(MODEL_CONFIG["top_p"]),
                "--top-k", str(MODEL_CONFIG["top_k"]),
                "--repeat-penalty", str(MODEL_CONFIG["repeat_penalty"]),
                "--n-predict", str(MODEL_CONFIG["max_tokens"]),
            ]

            # Add stop tokens
            for stop in MODEL_CONFIG.get("stop", []):
                cmd.extend(["--reverse-prompt", stop])

            # Start process
            log_file = Path.home() / ".codey-v2" / "llama-server-uds.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)

            with open(log_file, "w") as f:
                f.write(f"Starting llama-server (Unix socket): {' '.join(cmd)}\n")

            log_fd = open(log_file, "a")

            self._process = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )

            info(f"Unix socket: llama-server PID {self._process.pid}")

            # Wait for socket to be ready
            for i in range(120):  # 60 second timeout
                time.sleep(0.5)
                if socket_file.exists():
                    time.sleep(0.5)  # Extra moment to initialize
                    success(f"Unix socket: Server ready on {self._socket_path}")
                    return True

                if self._process.poll() is not None:
                    error(f"Unix socket: Server died with code {self._process.returncode}")
                    return False

            error("Unix socket: Timeout waiting for socket")
            return False

        except Exception as e:
            error(f"Unix socket: Failed to start server: {e}")
            return False

    def _is_tcp_server_running(self, host: str = "127.0.0.1", port: int = 8080) -> bool:
        """
        Check if llama-server is already running on TCP port.

        This prevents starting duplicate servers when daemon is running.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def stop_server(self):
        """Stop llama-server process."""
        if hasattr(self, '_process') and self._process:
            import signal
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                self._process.wait(timeout=5)
                info("Unix socket: Server stopped")
            except Exception as e:
                warning(f"Unix socket: Error stopping server: {e}")
                self._process.kill()
    
    def infer(self, prompt: str, max_tokens: int = 1024, stop: List[str] = None) -> Optional[str]:
        """
        Run inference via Unix socket HTTP.
        
        Uses urllib with custom socket connection.
        """
        try:
            start = time.time()
            
            # Build request
            data = {
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": MODEL_CONFIG["temperature"],
                "top_p": MODEL_CONFIG["top_p"],
                "top_k": MODEL_CONFIG["top_k"],
                "repeat_penalty": MODEL_CONFIG["repeat_penalty"],
                "stop": stop or [],
                "stream": False,
            }
            
            # Create Unix socket connection
            class UnixSocketHTTPHandler(urllib.request.HTTPHandler):
                def __init__(self, socket_path):
                    self.socket_path = socket_path
                
                def http_open(self, req):
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.connect(self.socket_path)
                    return self._make_response(sock, req)
                
                def _make_response(self, sock, req):
                    import http.client
                    conn = http.client.HTTPConnection("localhost")
                    conn.sock = sock
                    return conn.getresponse()
            
            # Install handler
            opener = urllib.request.build_opener(UnixSocketHTTPHandler(self._socket_path))
            urllib.request.install_opener(opener)
            
            # Make request
            req = urllib.request.Request(
                "http://localhost/completion",
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=300) as response:
                result = json.loads(response.read().decode('utf-8'))
                
            elapsed = time.time() - start
            info(f"Unix socket: Inference in {elapsed:.2f}s")
            
            return result.get("content", "").strip()
            
        except Exception as e:
            error(f"Unix socket: Inference failed: {e}")
            return None
    
    @property
    def backend_name(self) -> str:
        """Backend identifier."""
        return "unix_socket"


# =============================================================================
# TCP HTTP Backend (Original Fallback)
# =============================================================================

class TcpHttpBackend:
    """
    Original TCP localhost HTTP backend.
    
    Fallback when direct binding and Unix socket are unavailable.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self._host = host
        self._port = port
        self._base_url = f"http://{host}:{port}"
        self._process = None
    
    def start_server(self, model_path: Path, n_ctx: int = 4096, n_threads: int = 4) -> bool:
        """Start llama-server with TCP HTTP."""
        import subprocess
        
        try:
            info(f"TCP HTTP: Starting llama-server on {self._host}:{self._port}")
            
            cmd = [
                str(LLAMA_SERVER_BIN),
                "-m", str(model_path),
                "--host", self._host,
                "--port", str(self._port),
                "-c", str(n_ctx),
                "-t", str(n_threads),
                "--temp", str(MODEL_CONFIG["temperature"]),
                "--top-p", str(MODEL_CONFIG["top_p"]),
                "--top-k", str(MODEL_CONFIG["top_k"]),
                "--repeat-penalty", str(MODEL_CONFIG["repeat_penalty"]),
                "--n-predict", str(MODEL_CONFIG["max_tokens"]),
            ]
            
            for stop in MODEL_CONFIG.get("stop", []):
                cmd.extend(["--reverse-prompt", stop])
            
            log_file = Path.home() / ".codey-v2" / "llama-server-tcp.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(log_file, "w") as f:
                f.write(f"Starting llama-server (TCP): {' '.join(cmd)}\n")
            
            log_fd = open(log_file, "a")
            
            self._process = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )
            
            info(f"TCP HTTP: llama-server PID {self._process.pid}")
            
            # Wait for health check
            for i in range(120):
                time.sleep(0.5)
                if self._check_health():
                    time.sleep(0.5)
                    success(f"TCP HTTP: Server ready on {self._host}:{self._port}")
                    return True
                    
                if self._process.poll() is not None:
                    error(f"TCP HTTP: Server died with code {self._process.returncode}")
                    return False
            
            error("TCP HTTP: Timeout waiting for server")
            return False
            
        except Exception as e:
            error(f"TCP HTTP: Failed to start server: {e}")
            return False
    
    def stop_server(self):
        """Stop llama-server."""
        if self._process:
            import signal
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                self._process.wait(timeout=5)
                info("TCP HTTP: Server stopped")
            except Exception as e:
                warning(f"TCP HTTP: Error stopping server: {e}")
                self._process.kill()
    
    def _check_health(self) -> bool:
        """Check server health."""
        try:
            url = f"{self._base_url}/health"
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status == 200
        except:
            return False
    
    def infer(self, prompt: str, max_tokens: int = 1024, stop: List[str] = None) -> Optional[str]:
        """Run inference via TCP HTTP."""
        try:
            start = time.time()
            
            data = {
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": MODEL_CONFIG["temperature"],
                "top_p": MODEL_CONFIG["top_p"],
                "top_k": MODEL_CONFIG["top_k"],
                "repeat_penalty": MODEL_CONFIG["repeat_penalty"],
                "stop": stop or [],
                "stream": False,
            }
            
            req = urllib.request.Request(
                f"{self._base_url}/completion",
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=300) as response:
                result = json.loads(response.read().decode('utf-8'))
            
            elapsed = time.time() - start
            info(f"TCP HTTP: Inference in {elapsed:.2f}s")
            
            return result.get("content", "").strip()
            
        except Exception as e:
            error(f"TCP HTTP: Inference failed: {e}")
            return None
    
    @property
    def backend_name(self) -> str:
        return "tcp_http"


# =============================================================================
# Hybrid Backend Manager
# =============================================================================

@dataclass
class BackendStats:
    """Statistics for backend selection."""
    backend_name: str
    init_success: bool
    init_error: Optional[str] = None
    avg_latency_ms: float = 0.0
    calls_made: int = 0


class HybridInferenceBackend:
    """
    Manages hybrid inference backends with automatic fallback.
    
    Priority:
    1. Direct binding (llama-cpp-python) - if available
    2. Unix socket HTTP - if llama-server supports --socket
    3. TCP HTTP - always available fallback
    
    Logs backend selection and latency metrics.
    """
    
    def __init__(self, prefer_unix_socket: bool = True):
        self._direct = DirectBindingBackend()
        self._unix = UnixSocketBackend() if prefer_unix_socket else None
        self._tcp = TcpHttpBackend()
        
        self._active_backend = None
        self._loaded_model_path: Optional[Path] = None
        self._stats: Dict[str, BackendStats] = {}
        
        self._prefer_unix_socket = prefer_unix_socket
    
    def initialize(self) -> str:
        """
        Initialize available backends.

        Returns:
            Name of best available backend
        """
        # Try direct binding first
        direct_available = self._direct.initialize()
        self._stats["direct"] = BackendStats(
            backend_name="direct",
            init_success=direct_available,
            init_error=self._direct._init_error
        )

        if direct_available:
            info("Hybrid backend: Direct binding available (preferred)")
            self._active_backend = self._direct
            return "direct"

        # Try Unix socket
        if self._unix:
            # Check if llama-server is already running on TCP (e.g., from daemon or loader_v2)
            # If so, skip Unix socket and use TCP directly to avoid "socket not found" errors
            if self._unix._is_tcp_server_running():
                info("Hybrid backend: llama-server already running on TCP 8080, using TCP backend")
                self._stats["unix_socket"] = BackendStats(
                    backend_name="unix_socket",
                    init_success=False,
                    init_error="TCP server already running"
                )
                self._active_backend = self._tcp
                self._stats["tcp_http"] = BackendStats(
                    backend_name="tcp_http",
                    init_success=True
                )
                return "tcp_http"
            
            # Unix socket availability depends on llama-server --socket support
            # We'll try to start it when loading a model
            info("Hybrid backend: Unix socket available (secondary)")
            self._stats["unix_socket"] = BackendStats(
                backend_name="unix_socket",
                init_success=True
            )
            self._active_backend = self._unix
            return "unix_socket"

        # Fallback to TCP
        info("Hybrid backend: TCP HTTP available (fallback)")
        self._stats["tcp_http"] = BackendStats(
            backend_name="tcp_http",
            init_success=True
        )
        self._active_backend = self._tcp
        return "tcp_http"
    
    def load_model(self, model_path: Path, n_ctx: int = 4096, n_threads: int = 4) -> bool:
        """
        Load model using best available backend.
        
        Args:
            model_path: Path to GGUF model
            n_ctx: Context window
            n_threads: CPU threads
            
        Returns:
            True if loaded successfully
        """
        if not self._active_backend:
            error("Hybrid backend: No backend available")
            return False
        
        start = time.time()
        
        # Direct binding
        if isinstance(self._active_backend, DirectBindingBackend):
            success = self._active_backend.load_model(model_path, n_ctx, n_threads)
        
        # Unix socket
        elif isinstance(self._active_backend, UnixSocketBackend):
            success = self._active_backend.start_server(model_path, n_ctx, n_threads)
        
        # TCP HTTP
        elif isinstance(self._active_backend, TcpHttpBackend):
            success = self._active_backend.start_server(model_path, n_ctx, n_threads)
        
        else:
            error(f"Hybrid backend: Unknown backend type {type(self._active_backend)}")
            success = False
        
        if success:
            self._loaded_model_path = model_path
            elapsed = time.time() - start
            info(f"Hybrid backend: Model loaded via {self._active_backend.backend_name} in {elapsed:.1f}s")
        else:
            # Try fallback
            warning(f"Hybrid backend: {self._active_backend.backend_name} failed, trying fallback...")
            success = self._try_fallback(model_path, n_ctx, n_threads)
        
        return success
    
    def _try_fallback(self, model_path: Path, n_ctx: int, n_threads: int) -> bool:
        """Try fallback backends in priority order."""
        fallbacks = []
        
        if isinstance(self._active_backend, DirectBindingBackend):
            if self._unix:
                fallbacks.append(self._unix)
            fallbacks.append(self._tcp)
        elif isinstance(self._active_backend, UnixSocketBackend):
            fallbacks.append(self._tcp)
        
        for backend in fallbacks:
            warning(f"Hybrid backend: Trying fallback {backend.backend_name}...")
            
            if isinstance(backend, (UnixSocketBackend, TcpHttpBackend)):
                success = backend.start_server(model_path, n_ctx, n_threads)
            else:
                success = backend.load_model(model_path, n_ctx, n_threads)
            
            if success:
                self._active_backend = backend
                self._loaded_model_path = model_path
                success(f"Hybrid backend: Fallback to {backend.backend_name} successful")
                return True
        
        error("Hybrid backend: All backends failed")
        return False
    
    def unload_model(self):
        """Unload current model."""
        if not self._active_backend:
            return
        
        info(f"Hybrid backend: Unloading model from {self._active_backend.backend_name}")
        
        if isinstance(self._active_backend, DirectBindingBackend):
            self._active_backend.unload_model()
        elif isinstance(self._active_backend, (UnixSocketBackend, TcpHttpBackend)):
            self._active_backend.stop_server()
        
        self._loaded_model_path = None
    
    def infer(self, prompt: str, max_tokens: int = 1024, stop: List[str] = None) -> Optional[str]:
        """
        Run inference using active backend.
        
        Args:
            prompt: Formatted prompt
            max_tokens: Maximum tokens
            stop: Stop sequences
            
        Returns:
            Generated text or None
        """
        if not self._active_backend:
            error("Hybrid backend: No backend loaded")
            return None
        
        output = self._active_backend.infer(prompt, max_tokens, stop)
        
        if output:
            # Track stats
            stats = self._stats.get(self._active_backend.backend_name)
            if stats:
                stats.calls_made += 1
        
        return output
    
    @property
    def active_backend_name(self) -> str:
        """Get name of active backend."""
        return self._active_backend.backend_name if self._active_backend else "none"
    
    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        if not self._active_backend:
            return False
        
        if isinstance(self._active_backend, DirectBindingBackend):
            return self._active_backend.is_loaded
        return True  # HTTP backends are always "loaded" if server is running
    
    def get_stats(self) -> Dict[str, Any]:
        """Get backend statistics."""
        return {
            "active_backend": self.active_backend_name,
            "model_loaded": self._loaded_model_path.name if self._loaded_model_path else None,
            "backends": {
                name: {
                    "available": stats.init_success,
                    "error": stats.init_error,
                    "calls": stats.calls_made,
                }
                for name, stats in self._stats.items()
            }
        }


# Global singleton
_hybrid_backend: Optional[HybridInferenceBackend] = None


def get_hybrid_backend(prefer_unix_socket: bool = True) -> HybridInferenceBackend:
    """Get or create hybrid backend instance."""
    global _hybrid_backend
    if _hybrid_backend is None:
        _hybrid_backend = HybridInferenceBackend(prefer_unix_socket)
        _hybrid_backend.initialize()
    return _hybrid_backend


def reset_hybrid_backend():
    """Reset hybrid backend (for testing)."""
    global _hybrid_backend
    if _hybrid_backend:
        _hybrid_backend.unload_model()
        _hybrid_backend = None
