#!/usr/bin/env python3
"""
Dedicated embedding server for Codey-v2 knowledge base indexing.

Runs nomic-embed-text-v1.5 (80 MB Q4, 2048 ctx, 768-dim) as a separate
llama-server on port 8082 — distinct from the generation server on 8080/8081.

Benefits:
- 768-dim vectors — high quality cosine similarity
- 92.6% of chunks get hybrid BM25+vector; 7.4% (>2048 tok) use BM25 fallback
- Full 3777-chunk index builds in ~1 hour on S24 Ultra (~1s/chunk)
- Never evicted by model hot-swapping in loader_v2.py

Lifecycle:
- Auto-started by daemon (_main_loop) and inference.py (_start_server)
- Auto-restarted by daemon watchdog every 30s if dead
- Stopped on daemon shutdown or codeyd2 stop (pkill llama-server)

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
    nomic-embed-text-v1.5: 2048 ctx, 768-dim, 4 threads.
    """

    def __init__(self):
        self.model_path = EMBED_MODEL_PATH
        self.port = EMBED_SERVER_PORT
        self.process: Optional[subprocess.Popen] = None
        self._started = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the embed server subprocess. Idempotent."""
        # Already running as our own subprocess?
        if self.process and self.process.poll() is None and self._check_health():
            return True

        # Kill any stale llama-server occupying the embed port — it may have
        # different settings (wrong ctx, old ubatch) from a previous run.
        if self._is_port_open():
            info(f"Stale process on port {self.port} — replacing with fresh embed server...")
            self._kill_port_occupant()

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
            "-c", "2048",        # 2k ctx — fast for 92% of chunks; rest use BM25 fallback
            "-t", "4",           # 4 threads for embedding throughput
            "-b", "2048",        # logical batch size matches ctx
            "--ubatch-size", "2048",  # physical batch matches ctx
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

    def _kill_port_occupant(self):
        """Kill any llama-server bound to the embed port.

        Uses /proc scan to find the exact PID holding the port, avoiding
        unreliable pkill -f regex matching on Termux/Android.
        """
        import subprocess as _sp

        # Method 1: parse /proc/net/tcp to find PID on our port
        try:
            port_hex = f"{self.port:04X}"
            with open("/proc/net/tcp") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 10:
                        continue
                    local_addr = parts[1]
                    if local_addr.endswith(f":{port_hex}"):
                        inode = parts[9]
                        # Find PID owning this inode
                        for pid_dir in Path("/proc").iterdir():
                            if not pid_dir.name.isdigit():
                                continue
                            try:
                                for fd in (pid_dir / "fd").iterdir():
                                    link = os.readlink(str(fd))
                                    if f"socket:[{inode}]" in link:
                                        pid = int(pid_dir.name)
                                        info(f"Killing stale embed server PID {pid}")
                                        os.kill(pid, 9)
                                        raise StopIteration
                            except (PermissionError, StopIteration, OSError):
                                pass
                        break
        except StopIteration:
            pass
        except Exception:
            pass

        # Method 2: fallback — kill all llama-server processes
        # This is aggressive but reliable on Termux where fuser/lsof may not exist
        try:
            _sp.run(["pkill", "-9", "llama-server"], capture_output=True)
        except Exception:
            pass

        import time as _time
        _time.sleep(2)  # give kernel time to release the port

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
