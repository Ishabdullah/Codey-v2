#!/usr/bin/env python3
"""
Inference engine for Codey-v2 (v2.6.0 — ChatML fix).

Uses llama-server's /v1/chat/completions endpoint which automatically applies
the model's chat template. Previous versions sent raw text to /completion,
bypassing ChatML — the root cause of most instruction-following failures.

Falls back to legacy HTTP backend (core/inference.py) if hybrid is unavailable.
"""

import time
from typing import Optional, Dict, Any

from utils.logger import info, error, warning, success
from utils.config import MODEL_CONFIG
from core.loader_v2 import get_loader
from rich.console import Console
import sys

console = Console()

last_tps = 0.0

# Chat completions backend (v2.6.0)
_chat_backend = None

# Set to True after a streaming inference so callers can skip re-printing
_last_was_streamed = False


def was_last_streamed() -> bool:
    """Return True if the most recent infer() call used live streaming."""
    return _last_was_streamed


def _get_chat_backend():
    """Get chat completions backend (lazy initialization)."""
    global _chat_backend
    if _chat_backend is None:
        try:
            from core.inference_hybrid import get_hybrid_backend
            _chat_backend = get_hybrid_backend()
            info(f"Backend: {_chat_backend.backend_name}")
        except Exception as e:
            warning(f"Chat backend init failed: {e}, using HTTP fallback")
            _chat_backend = "http_fallback"
    return _chat_backend


def infer(messages: list[dict], stream: bool = False, extra_stop: list = None,
          model: str = None, show_thinking: bool = False,
          use_hybrid: bool = True) -> str:
    """
    Run inference using /v1/chat/completions (ChatML).

    Args:
        messages: Chat messages [{"role": "system"/"user"/"assistant", "content": "..."}]
        stream: Enable streaming (reserved for future use)
        extra_stop: Additional stop sequences
        model: Ignored (single-model mode — always uses primary 7B)
        show_thinking: Show thinking indicator
        use_hybrid: Use chat completions backend (default True)

    Returns:
        Generated text or error message
    """
    global last_tps

    # Ensure model is loaded
    loader = get_loader()
    if not loader.ensure_model():
        return "[ERROR] Failed to load model"

    # Try chat completions backend (v2.6.0)
    if use_hybrid:
        backend = _get_chat_backend()
        if backend and backend != "http_fallback":
            try:
                return _infer_chat(backend, messages, extra_stop, show_thinking, stream)
            except Exception as e:
                warning(f"Chat completions failed: {e}, falling back to HTTP")

    # Legacy HTTP fallback
    return _infer_http(messages, stream, extra_stop, show_thinking)


def _infer_chat(backend, messages: list[dict], extra_stop: list,
                show_thinking: bool, stream: bool = False) -> str:
    """Run inference via /v1/chat/completions — proper ChatML."""
    global last_tps, _last_was_streamed

    # Build stop tokens
    stop = list(MODEL_CONFIG.get("stop", []))
    if extra_stop:
        stop.extend(s for s in extra_stop if s not in stop)

    if show_thinking:
        console.print("[dim]\u2901 Thinking...[/dim]")

    start = time.time()
    result = backend.infer(messages, max_tokens=MODEL_CONFIG.get("max_tokens", 2048),
                           stop=stop, stream=stream)

    if result is None:
        _last_was_streamed = False
        return "[ERROR] Chat completions inference failed"

    # result is (text, tokens, tps) tuple
    text, tokens, tps = result
    elapsed = time.time() - start
    last_tps = tps
    _last_was_streamed = stream

    # When streaming, tokens were already printed live — skip the "Done" line
    # to avoid cluttering the output. For blocking mode, show the summary.
    if show_thinking and not stream:
        bname = backend.backend_name
        console.print(f"[dim]\u2713 Done ({bname}): {tokens} tokens in {elapsed:.1f}s ({tps:.1f} t/s)[/dim]")

    return text


def _infer_http(messages: list[dict], stream: bool, extra_stop: list,
                show_thinking: bool) -> str:
    """Run inference using legacy HTTP backend (inference.py on port 8081)."""
    global last_tps

    from core.inference import infer as legacy_infer

    if show_thinking:
        console.print("[dim]\u2901 Thinking (HTTP fallback)...[/dim]")

    start = time.time()
    result = legacy_infer(messages, stream=stream, extra_stop=extra_stop)
    elapsed = time.time() - start

    if show_thinking and result and not result.startswith("[ERROR]"):
        tokens = len(result.split())
        tps = round(tokens / elapsed, 1) if elapsed > 0 else 0
        last_tps = tps
        console.print(f"[dim]\u2713 Done (http): {tokens} tokens in {elapsed:.1f}s ({tps:.1f} t/s)[/dim]")

    return result


def get_model_status() -> dict:
    """Get current model status."""
    loader = get_loader()

    status = {
        "loaded": loader.get_loaded_model(),
        "loader": loader.get_status(),
    }

    backend = _chat_backend
    if backend and backend != "http_fallback":
        try:
            status["backend"] = backend.get_stats()
        except Exception:
            pass

    return status


def get_backend_info() -> Dict[str, Any]:
    """Get information about the active inference backend."""
    backend = _get_chat_backend()

    if backend == "http_fallback" or backend is None:
        return {
            "type": "http",
            "method": "llama-server + /v1/chat/completions (legacy port 8081)",
            "note": "Chat backend unavailable, using HTTP fallback"
        }

    return {
        "type": backend.backend_name,
        "method": "llama-server + /v1/chat/completions (ChatML)",
        "port": backend._port,
        "calls_made": backend._calls_made,
    }
