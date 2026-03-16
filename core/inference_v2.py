#!/usr/bin/env python3
"""Inference engine for Codey-v2 with dual-model support (Termux compatible).

Hybrid backend (v2.4.0):
- Attempts direct llama-cpp-python binding first (~50-100ms overhead)
- Falls back to Unix domain socket HTTP (~200-300ms overhead)
- Final fallback to TCP localhost HTTP (~500ms overhead)

Backend selection is automatic with graceful degradation.
Logs backend used and latency metrics for observability.

Original HTTP API backend still available for compatibility.
"""

import time
from typing import Optional, Dict, Any

from utils.logger import info, error, warning, success
from utils.config import MODEL_CONFIG
from core.loader_v2 import get_loader
from core.router import get_router
from rich.console import Console
import sys

console = Console()

last_tps = 0.0

# Hybrid backend (v2.4.0) - lazy import to avoid breaking existing installs
_hybrid_backend = None

def _get_hybrid_backend():
    """Get hybrid backend instance (lazy initialization)."""
    global _hybrid_backend
    if _hybrid_backend is None:
        try:
            from core.inference_hybrid import get_hybrid_backend as _get_backend
            _hybrid_backend = _get_backend(prefer_unix_socket=True)
            info(f"Hybrid backend initialized: {_hybrid_backend.active_backend_name}")
        except Exception as e:
            warning(f"Hybrid backend init failed: {e}, using HTTP fallback")
            _hybrid_backend = "http_fallback"
    return _hybrid_backend


def infer(messages: list[dict], stream: bool = False, extra_stop: list = None, 
        model: str = None, show_thinking: bool = False, 
        use_hybrid: bool = True) -> str:
    """
    Run inference with optional model selection and thinking display.
    
    Args:
        messages: Chat messages list
        stream: Enable streaming (not yet implemented)
        extra_stop: Additional stop sequences
        model: Force specific model ("primary" or "secondary")
        show_thinking: Show thinking indicator
        use_hybrid: Use hybrid backend if available (default True)
        
    Returns:
        Generated text or error message
    """
    global last_tps

    # Try hybrid backend first (v2.4.0)
    if use_hybrid:
        backend = _get_hybrid_backend()
        if backend and backend != "http_fallback":
            try:
                return _infer_hybrid(backend, messages, extra_stop, model, show_thinking)
            except Exception as e:
                warning(f"Hybrid inference failed: {e}, falling back to HTTP")
                # Fall through to HTTP backend
    
    # HTTP backend (original, reliable fallback)
    return _infer_http(messages, stream, extra_stop, model, show_thinking)


def _infer_hybrid(backend, messages: list[dict], extra_stop: list, 
                  model: str, show_thinking: bool) -> str:
    """Run inference using hybrid backend."""
    global last_tps
    
    loader = get_loader()
    
    # Auto-route if model not specified
    if model is None:
        user_input = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_input = msg.get("content", "")
                break
        model = get_router().route_task(user_input)
        info(f"Auto-routed to {model} model")
    
    # Ensure model is loaded via loader (manages hot-swap)
    start = time.time()
    if not loader.ensure_model(model):
        return f"[ERROR] Failed to load {model} model"
    
    load_time = time.time() - start
    if load_time > 1:
        info(f"Model swap took {load_time:.1f}s")
    
    # Build stop tokens
    stop = list(MODEL_CONFIG.get("stop", []))
    if extra_stop:
        stop.extend(extra_stop)
    
    # Extract system message
    system = ""
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system = msg.get("content", "")
        else:
            user_messages.append(msg)
    
    # Format prompt
    prompt = ""
    if system:
        prompt += f"System: {system}\n\n"
    for msg in user_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt += f"{role.capitalize()}: {content}\n\n"
    prompt += "Assistant:"
    
    # Show thinking indicator
    if show_thinking:
        console.print("[dim]⠋ Thinking...[/dim]")
    
    # Run inference
    start = time.time()
    output = backend.infer(prompt, max_tokens=MODEL_CONFIG.get("max_tokens", 1024), stop=stop)
    
    if output is None:
        return "[ERROR] Hybrid inference failed"
    
    elapsed = time.time() - start
    tokens = len(output.split())
    last_tps = tokens / elapsed if elapsed > 0 else 0
    
    # Show stats
    if show_thinking:
        console.print(f"[dim]✓ Done ({backend.active_backend_name}): {tokens} tokens in {elapsed:.1f}s ({last_tps:.1f} t/s)[/dim]")
    
    info(f"Hybrid inference ({backend.active_backend_name}): {tokens} tokens in {elapsed:.1f}s ({last_tps:.1f} t/s)")
    
    return output.strip()


def _infer_http(messages: list[dict], stream: bool, extra_stop: list, 
                model: str, show_thinking: bool) -> str:
    """Run inference using original HTTP backend."""
    global last_tps

    loader = get_loader()

    # Auto-route if model not specified
    if model is None:
        user_input = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_input = msg.get("content", "")
                break
        model = get_router().route_task(user_input)
        info(f"Auto-routed to {model} model")

    # Ensure model is loaded
    start = time.time()
    if not loader.ensure_model(model):
        return f"[ERROR] Failed to load {model} model"

    load_time = time.time() - start
    if load_time > 1:
        info(f"Model swap took {load_time:.1f}s")

    # Get llama-server instance
    server = loader.get_model_instance()
    if not server:
        return "[ERROR] No model loaded"

    # Build stop tokens
    stop = list(MODEL_CONFIG.get("stop", []))
    if extra_stop:
        stop.extend(extra_stop)

    # Extract system message if present
    system = ""
    user_messages = []
    for msg in messages:
        if msg.get("role") == "system":
            system = msg.get("content", "")
        else:
            user_messages.append(msg)

    # Format prompt for llama-server
    prompt = ""
    if system:
        prompt += f"System: {system}\n\n"
    for msg in user_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt += f"{role.capitalize()}: {content}\n\n"
    prompt += "Assistant:"

    # Show simple thinking indicator (no threads, safe for Termux)
    if show_thinking:
        console.print("[dim]⠋ Thinking...[/dim]")

    # Run inference
    start = time.time()
    try:
        output = server.infer(prompt, max_tokens=MODEL_CONFIG.get("max_tokens", 1024), stop=stop)

        if output is None:
            return "[ERROR] Inference failed"

        elapsed = time.time() - start
        tokens = len(output.split())
        last_tps = tokens / elapsed if elapsed > 0 else 0

        # Clear thinking line and show stats
        if show_thinking:
            console.print(f"[dim]✓ Done: {tokens} tokens in {elapsed:.1f}s ({last_tps:.1f} t/s)[/dim]")

        info(f"Inference (HTTP): {tokens} tokens in {elapsed:.1f}s ({last_tps:.1f} t/s)")

        return output.strip()

    except Exception as e:
        error(f"Inference error: {e}")
        return f"[ERROR] {e}"


def get_model_status() -> dict:
    """Get current model status."""
    loader = get_loader()
    router = get_router()
    
    status = {
        "loaded": loader.get_loaded_model(),
        "router": router.get_status(),
        "loader": loader.get_status(),
    }
    
    # Add hybrid backend info if available
    backend = _hybrid_backend
    if backend and backend != "http_fallback":
        try:
            status["hybrid_backend"] = backend.get_stats()
        except:
            pass
    
    return status


def get_backend_info() -> Dict[str, Any]:
    """
    Get information about the active inference backend.
    
    Returns:
        Dict with backend type, latency, and capabilities
    """
    backend = _get_hybrid_backend()
    
    if backend == "http_fallback" or backend is None:
        return {
            "type": "http",
            "method": "llama-server subprocess + HTTP API",
            "overhead_ms": "~500ms per call",
            "note": "Hybrid backend unavailable, using HTTP fallback"
        }
    
    try:
        stats = backend.get_stats()
        return {
            "type": stats["active_backend"],
            "method": _get_backend_method(stats["active_backend"]),
            "overhead_ms": _get_backend_overhead(stats["active_backend"]),
            "backends_available": list(stats["backends"].keys()),
        }
    except Exception as e:
        return {
            "type": "unknown",
            "error": str(e),
            "fallback": "http"
        }


def _get_backend_method(backend_type: str) -> str:
    """Get human-readable backend method description."""
    methods = {
        "direct": "llama-cpp-python direct binding",
        "unix_socket": "llama-server + Unix domain socket HTTP",
        "tcp_http": "llama-server + TCP localhost HTTP",
    }
    return methods.get(backend_type, "unknown")


def _get_backend_overhead(backend_type: str) -> str:
    """Get typical overhead for backend type."""
    overheads = {
        "direct": "~50-100ms per call",
        "unix_socket": "~200-300ms per call",
        "tcp_http": "~400-600ms per call",
    }
    return overheads.get(backend_type, "unknown")
