#!/usr/bin/env python3
"""
Inference backend for Codey-v2 (v2.6.0 — simplified).

Uses llama-server's /v1/chat/completions endpoint which automatically applies
the model's chat template (ChatML for Qwen2.5-Coder). This is CRITICAL —
sending raw prompts to /completion bypasses the template and the model cannot
distinguish system instructions from user messages.

Backend: TCP HTTP to llama-server on port 8080 (started by loader_v2 or daemon).
"""

import os
import time
import socket
import urllib.request
import urllib.error
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from utils.logger import info, warning, error, success
from utils.config import MODEL_CONFIG


class ChatCompletionBackend:
    """
    HTTP backend using llama-server's /v1/chat/completions endpoint.

    Uses proper messages array so llama-server applies the model's chat
    template (ChatML for Qwen2.5-Coder). This is the only backend needed
    on Termux/Android where llama-server runs on TCP port 8080.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self._host = host
        self._port = port
        self._base_url = f"http://{host}:{port}"
        self._calls_made = 0

    def check_health(self) -> bool:
        """Check if llama-server is responding."""
        try:
            url = f"{self._base_url}/health"
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def is_server_running(self) -> bool:
        """Check if llama-server is listening on the TCP port."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((self._host, self._port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def infer(self, messages: list, max_tokens: int = 2048,
              stop: List[str] = None) -> Optional[str]:
        """
        Run inference via /v1/chat/completions.

        Args:
            messages: Chat messages list [{"role": "system", "content": "..."},
                      {"role": "user", "content": "..."}, ...]
            max_tokens: Maximum tokens to generate
            stop: Additional stop sequences

        Returns:
            Generated text or None on error
        """
        try:
            start = time.time()

            # Build stop tokens
            stop_tokens = list(MODEL_CONFIG.get("stop", []))
            if stop:
                stop_tokens.extend(s for s in stop if s not in stop_tokens)

            payload = {
                "model": "codey",
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": MODEL_CONFIG["temperature"],
                "top_p": MODEL_CONFIG["top_p"],
                "top_k": MODEL_CONFIG["top_k"],
                "repeat_penalty": MODEL_CONFIG["repeat_penalty"],
                "stop": stop_tokens,
                "stream": False,
            }

            req = urllib.request.Request(
                f"{self._base_url}/v1/chat/completions",
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=300) as response:
                result = json.loads(response.read().decode('utf-8'))

            elapsed = time.time() - start
            self._calls_made += 1

            # Extract response text
            text = result["choices"][0]["message"]["content"]

            # Extract token stats if available
            tokens = 0
            tps = 0.0
            if "usage" in result:
                tokens = result["usage"].get("completion_tokens", 0)
            if "timings" in result:
                t = result["timings"]
                predicted = t.get("predicted_n", 0)
                ms = t.get("predicted_ms", 0)
                if ms > 0:
                    tps = round((predicted / ms) * 1000, 1)
                    tokens = predicted

            if not tokens:
                tokens = len(text.split())  # rough fallback

            if not tps and elapsed > 0:
                tps = round(tokens / elapsed, 1)

            info(f"Chat completions: {tokens} tokens in {elapsed:.1f}s ({tps:.1f} t/s)")

            return text.strip(), tokens, tps

        except urllib.error.URLError as e:
            error(f"Chat completions failed: {e}")
            return None
        except Exception as e:
            error(f"Chat completions failed: {e}")
            return None

    @property
    def backend_name(self) -> str:
        return "chat_completions"

    def get_stats(self) -> Dict[str, Any]:
        return {
            "active_backend": self.backend_name,
            "host": self._host,
            "port": self._port,
            "calls_made": self._calls_made,
        }


# Global singleton
_backend: Optional[ChatCompletionBackend] = None


def get_hybrid_backend(prefer_unix_socket: bool = True) -> ChatCompletionBackend:
    """Get or create the chat completions backend.

    The prefer_unix_socket parameter is kept for backward compatibility
    but ignored — we always use TCP HTTP with /v1/chat/completions.
    """
    global _backend
    if _backend is None:
        _backend = ChatCompletionBackend()
        if _backend.is_server_running():
            info(f"Chat completions backend: llama-server on {_backend._host}:{_backend._port}")
        else:
            warning("Chat completions backend: llama-server not detected on port 8080")
    return _backend


def reset_hybrid_backend():
    """Reset backend (for testing)."""
    global _backend
    _backend = None
