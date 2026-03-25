#!/usr/bin/env python3
"""
plannd — Planner Daemon for Codey-v2

Runs DeepSeek-R1-Distill-Qwen-1.5B as a dedicated task-planning model on port 8081.
Listens on a Unix socket (plannd.sock), accepts raw user tasks, and returns a
numbered checklist of concrete steps for the main 7B model to execute.

Design constraints:
- This process is intentionally minimal: plan tasks, nothing else.
- If plannd crashes or fails to start, the main codeyd2 daemon continues
  using the existing planner_v2.py heuristic fallback. plannd failure is
  never fatal to the main daemon.
- PID file: ~/.codey-v2/plannd.pid
- Log file: ~/.codey-v2/plannd.log  (stdout/stderr captured by codeyd2)
- Socket:   ~/.codey-v2/plannd.sock
- Port:     8081 (DeepSeek llama-server)
"""

import os
import sys
import json
import asyncio
import signal
import subprocess
import time
import urllib.request
import urllib.error
import re
from pathlib import Path
from typing import Optional, List

# ── Paths (overridden below from config once sys.path is set up) ─────────────
DAEMON_DIR  = Path.home() / ".codey-v2"
PID_FILE    = DAEMON_DIR / "plannd.pid"
SOCKET_FILE = DAEMON_DIR / "plannd.sock"

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8081

# The exact system prompt requested — do not modify without updating config docs.
PLANNER_SYSTEM_PROMPT = (
    "You are a task planner. Your only job is to break the following "
    "request into a precise numbered checklist of steps for a coding "
    "assistant to execute one at a time.\n\n"
    "Rules:\n"
    "- Each step is one single concrete action\n"
    "- Steps must be in the correct order\n"
    "- Include a run or verify step after every file that is created\n"
    "- Include a test step after any code is written\n"
    "- Never write code yourself\n"
    "- Never explain anything\n"
    "- Output the numbered list only and nothing else"
)


# ── Step parser ───────────────────────────────────────────────────────────────

def parse_steps(raw: str) -> List[str]:
    """
    Extract numbered steps from DeepSeek output.

    DeepSeek-R1 models emit <think>...</think> before the actual answer.
    We strip those first, then collect lines matching "N. step" or "N) step".
    """
    # Remove thinking block (DeepSeek-R1 reasoning trace)
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    steps: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+)[.)]\s+(.+)$", line)
        if m:
            step = m.group(2).strip()
            if step:
                steps.append(step)
    return steps


# ── DeepSeek llama-server wrapper ────────────────────────────────────────────

class DeepSeekServer:
    """
    Manages a llama-server subprocess for the DeepSeek 1.5B model on port 8081.

    Intentionally NOT using mmap — the model runs briefly and exits so there
    is no benefit to demand-paging for a short-lived planning session.
    """

    def __init__(self, model_path: Path, port: int, llama_bin: str):
        self.model_path = model_path
        self.port = port
        self.llama_bin = llama_bin
        self.process: Optional[subprocess.Popen] = None
        self._started = False

    def start(self) -> bool:
        """Start DeepSeek llama-server on port 8081."""
        try:
            if self.process and self.process.poll() is None:
                return True

            if self._is_port_in_use():
                print(f"[plannd] llama-server already on port {self.port}, reusing", flush=True)
                self._started = True
                return True

            if not self.model_path.exists():
                print(f"[plannd] ERROR: model not found: {self.model_path}", flush=True)
                return False

            llama = Path(self.llama_bin)
            if not llama.exists():
                print(f"[plannd] ERROR: llama-server not found: {self.llama_bin}", flush=True)
                return False

            print(f"[plannd] Starting DeepSeek server on port {self.port}...", flush=True)

            cmd = [
                str(self.llama_bin),
                "-m", str(self.model_path),
                "--host", SERVER_HOST,
                "--port", str(self.port),
                "-c", "8192",       # 8K context — enough for planning
                "-t", "4",          # 4 threads
                "--temp", "0.3",    # Low temperature for deterministic plans
                "--top-p", "0.9",
                "--top-k", "20",
                "--repeat-penalty", "1.1",
                "--n-predict", "512",   # Plans are short
                "--flash-attn", "on",
                # Do NOT add --mmap — short-lived process, not worth it
            ]

            log_dir = DAEMON_DIR
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "plannd-llama.log"

            with open(log_path, "w") as lf:
                lf.write(f"[plannd] cmd: {' '.join(cmd)}\n")

            log_fd = open(log_path, "a")
            self.process = subprocess.Popen(
                cmd,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid if os.name != "nt" else None,
            )

            print(f"[plannd] DeepSeek server PID: {self.process.pid}", flush=True)

            # Wait up to 60s for the server to become healthy
            for _ in range(120):
                time.sleep(0.5)
                if self.process.poll() is not None:
                    print(f"[plannd] ERROR: DeepSeek server exited (code {self.process.poll()})",
                          flush=True)
                    return False
                if self._check_health():
                    self._started = True
                    print(f"[plannd] DeepSeek server ready on port {self.port}", flush=True)
                    return True

            print("[plannd] ERROR: Timeout waiting for DeepSeek server", flush=True)
            self.stop()
            return False

        except Exception as e:
            print(f"[plannd] ERROR starting server: {e}", flush=True)
            return False

    def stop(self):
        """Stop the DeepSeek llama-server subprocess."""
        if self.process:
            try:
                if os.name != "nt":
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    except ProcessLookupError:
                        self.process.terminate()
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            finally:
                self.process = None
                self._started = False

    def _check_health(self) -> bool:
        try:
            url = f"http://{SERVER_HOST}:{self.port}/health"
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _is_port_in_use(self) -> bool:
        import socket as _sock
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(1.0)
            result = s.connect_ex((SERVER_HOST, self.port))
            s.close()
            if result == 0:
                return self._check_health()
            return False
        except Exception:
            return False

    def infer(self, task: str) -> Optional[str]:
        """
        Call DeepSeek via /v1/chat/completions and return raw text output.
        This is a blocking call — run it in an executor from async code.
        Timeout is set to 40s (slightly under the 45s plannd socket timeout).
        """
        if not self._started:
            return None

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user",   "content": task},
        ]
        payload = {
            "model": "plannd",
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.3,
            "top_p": 0.9,
            "top_k": 20,
            "repeat_penalty": 1.1,
            "stop": ["<|im_end|>", "<|im_start|>", "\nUser:", "\nHuman:"],
            "stream": False,
        }

        url = f"http://{SERVER_HOST}:{self.port}/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=40) as response:
                result = json.loads(response.read().decode("utf-8"))
                choices = result.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            print(f"[plannd] inference error: {e}", flush=True)
        return None


# ── Unix socket server ────────────────────────────────────────────────────────

class PlannDServer:
    """
    Asyncio Unix socket server.

    Protocol (same framing as the main daemon):
      Client → Server: JSON bytes {"task": "..."}, then closes write side.
      Server → Client: JSON bytes {"steps": [...]} or {"error": "..."}, then closes.
    """

    def __init__(self, deepseek: DeepSeekServer):
        self.deepseek = deepseek
        self.server: Optional[asyncio.AbstractServer] = None

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        try:
            data = await reader.read(65536)
            if not data:
                return

            request = json.loads(data.decode("utf-8"))
            task = request.get("task", "").strip()

            if not task:
                response = {"error": "no task provided"}
            else:
                # Run blocking inference in a thread so we don't stall the loop
                loop = asyncio.get_running_loop()
                raw = await loop.run_in_executor(None, self.deepseek.infer, task)

                if raw:
                    steps = parse_steps(raw)
                    if steps:
                        response = {"steps": steps}
                        print(f"[plannd] plan: {len(steps)} steps for task", flush=True)
                    else:
                        response = {"error": "no numbered steps found in model output"}
                        print(f"[plannd] WARNING: model output had no steps:\n{raw[:200]}", flush=True)
                else:
                    response = {"error": "inference returned empty result"}

        except json.JSONDecodeError as e:
            response = {"error": f"invalid JSON from client: {e}"}
        except Exception as e:
            response = {"error": str(e)}
            print(f"[plannd] handler error: {e}", flush=True)

        try:
            writer.write(json.dumps(response).encode("utf-8"))
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def serve(self):
        """Start the socket server and serve until the event loop is stopped."""
        SOCKET_FILE.unlink(missing_ok=True)

        self.server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(SOCKET_FILE),
        )
        os.chmod(str(SOCKET_FILE), 0o600)
        print(f"[plannd] Listening on {SOCKET_FILE}", flush=True)

        async with self.server:
            await self.server.serve_forever()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    """
    Launch plannd.

    1. Set up paths from utils.config (falls back to hard-coded defaults).
    2. Write PID file.
    3. Start DeepSeek llama-server on port 8081.
    4. Run asyncio socket server until SIGTERM.
    """
    global SOCKET_FILE, SERVER_PORT

    DAEMON_DIR.mkdir(parents=True, exist_ok=True)

    # Resolve config — sys.path is already set up by the codeyd2 launcher
    llama_bin = "llama-server"   # fallback
    model_path = (
        Path.home() / "models" / "DeepSeek-R1-1.5B"
        / "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf"
    )
    try:
        from utils.config import (
            DEEPSEEK_MODEL_PATH,
            PLANND_SOCKET_PATH,
            PLANND_SERVER_PORT,
            LLAMA_SERVER_BIN,
        )
        model_path  = DEEPSEEK_MODEL_PATH
        SOCKET_FILE = PLANND_SOCKET_PATH
        SERVER_PORT = PLANND_SERVER_PORT
        llama_bin   = LLAMA_SERVER_BIN
        print(f"[plannd] Config loaded. Model: {model_path.name}", flush=True)
    except ImportError as e:
        print(f"[plannd] WARNING: could not import config ({e}), using defaults", flush=True)

    # Write PID immediately so codeyd2 can track us
    PID_FILE.write_text(str(os.getpid()))
    print(f"[plannd] PID {os.getpid()}", flush=True)

    # Start DeepSeek server
    deepseek = DeepSeekServer(model_path, SERVER_PORT, llama_bin)
    if not deepseek.start():
        print("[plannd] FATAL: DeepSeek server failed to start — exiting", flush=True)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    server = PlannDServer(deepseek)

    # Set up asyncio loop with signal handlers for clean shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown():
        print("[plannd] Shutdown signal received", flush=True)
        deepseek.stop()
        SOCKET_FILE.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        loop.stop()

    loop.add_signal_handler(signal.SIGTERM, _shutdown)
    loop.add_signal_handler(signal.SIGINT,  _shutdown)

    try:
        loop.run_until_complete(server.serve())
    except Exception as e:
        print(f"[plannd] Server error: {e}", flush=True)
    finally:
        deepseek.stop()
        SOCKET_FILE.unlink(missing_ok=True)
        PID_FILE.unlink(missing_ok=True)
        loop.close()
        print("[plannd] Stopped", flush=True)


if __name__ == "__main__":
    main()
