#!/usr/bin/env python3
"""
Dedicated embedding server for Codey-v2 knowledge base indexing.

Runs nomic-embed-text (or any small GGUF) as a separate llama-server
instance on port 8082 — distinct from the generation server on 8080.

Benefits:
- Purpose-built encoder model: ~80 MB, ~50 ms/chunk (vs 7B at ~3 s/chunk)
- Never evicted by model hot-swapping in loader_v2.py
- Generation and embedding run concurrently if needed

The embed server is started automatically by the daemon in _main_loop()
and stopped on daemon shutdown (or via pkill -f llama-server).

Usage:
    from core.embed_server import get_embed_server, start_embed_server
    ok = start_embed_server()   # idempotent — safe to call multiple times
"""

import os
import subprocess
import time
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from utils.logger import info, warning, error, success
from utils.config import LLAMA_SERVER_BIN, EMBED_MODEL_PATH, EMBED_SERVER_PORT

# Host is always localhost
_HOST = "127.0.0.1"


class EmbedServer:
    """
    Manages a dedicated llama-server subprocess for embeddings only.

    Uses --embedding --pooling mean to expose /v1/embeddings in OAI format.
    Minimal context window (2048) and thread count (2) to keep RAM low while
    the primary 7B model is also loaded.
    """

    def __init__(self):
        self.model_path = EMBED_MODEL_PATH
        self.port = EMBED_SERVER_PORT
        self.process: Optional[subprocess.Popen] = None
        self._started = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the embed server subprocess. Idempotent."""
        # Already running?
        if self._started and self._check_health():
            return True

        # Another process already serving on this port?
        if self._is_port_open():
            info(f"Embed server already running on port {self.port}")
            self._started = True
            return True

        if not self.model_path.exists():
            warning(f"Embed model not found: {self.model_path}")
            warning("Run: bash tools/setup_skills.sh   to set up the embedding model")
            return False

        llama_bin = Path(LLAMA_SERVER_BIN)
        if not llama_bin.exists():
            error(f"llama-server binary not found: {LLAMA_SERVER_BIN}")
            return False

        info(f"Starting embed server (nomic) on port {self.port}...")

        cmd = [
            str(llama_bin),
            "-m", str(self.model_path),
            "--host", _HOST,
            "--port", str(self.port),
            "-c", "16384",      # 16k context — handles long KB chunks
            "-t", "4",          # 4 threads for embedding throughput
            "--embedding",      # enable /v1/embeddings endpoint
            "--pooling", "mean",# OAI-compatible single vector per input
        ]

        log_file = Path.home() / ".codey-v2" / "embed-server.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        log_fd = open(log_file, "a")
        log_fd.write(f"\n--- embed server start: {' '.join(cmd)}\n")
        log_fd.flush()

        self.process = subprocess.Popen(
            cmd,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid if os.name != "nt" else None,
        )

        info(f"Embed server PID: {self.process.pid}, log: {log_file}")

        # Wait up to 30 s for the server to become healthy
        for _ in range(60):
            time.sleep(0.5)
            if self.process.poll() is not None:
                error(f"Embed server died (exit {self.process.poll()})")
                try:
                    with open(log_file) as f:
                        tail = f.read()[-800:]
                    error(f"Embed log tail:\n{tail}")
                except Exception:
                    pass
                return False
            if self._check_health():
                self._started = True
                success(f"Embed server ready on port {self.port}")
                return True

        error("Timeout waiting for embed server")
        self.stop()
        return False

    def stop(self):
        """Stop the embed server subprocess."""
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
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(self.process.pid), _signal.SIGKILL)
                    except Exception:
                        self.process.kill()
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                self.process = None
                self._started = False
                info("Embed server stopped")

    def is_running(self) -> bool:
        if self.process is not None and self.process.poll() is None:
            return True
        if self._started:
            return self._check_health()
        return False

    # ── Health helpers ─────────────────────────────────────────────────────────

    def _check_health(self) -> bool:
        try:
            url = f"http://{_HOST}:{self.port}/health"
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _is_port_open(self) -> bool:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            result = s.connect_ex((_HOST, self.port))
            s.close()
            if result == 0:
                return self._check_health()
            return False
        except Exception:
            return False


# ── Global singleton ───────────────────────────────────────────────────────────

_embed_server: Optional[EmbedServer] = None


def get_embed_server() -> EmbedServer:
    global _embed_server
    if _embed_server is None:
        _embed_server = EmbedServer()
    return _embed_server


def start_embed_server() -> bool:
    """Start the global embed server. Idempotent."""
    return get_embed_server().start()


def stop_embed_server():
    """Stop the global embed server."""
    global _embed_server
    if _embed_server is not None:
        _embed_server.stop()
        _embed_server = None
