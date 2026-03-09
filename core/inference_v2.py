#!/usr/bin/env python3
"""Inference engine for Codey-v2 with dual-model support (Termux compatible).

Uses llama-server HTTP API instead of llama-cpp-python bindings.
"""

import time
from utils.logger import info, error
from utils.config import MODEL_CONFIG
from core.loader_v2 import get_loader
from core.router import get_router
from rich.console import Console
import sys

console = Console()

last_tps = 0.0

def infer(messages: list[dict], stream: bool = False, extra_stop: list = None, model: str = None, show_thinking: bool = False) -> str:
    """Run inference with optional model selection and thinking display."""
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
        output = server.infer(prompt, max_tokens=MODEL_CONFIG.get("max_tokens", 1024))

        if output is None:
            return "[ERROR] Inference failed"

        elapsed = time.time() - start
        tokens = len(output.split())
        last_tps = tokens / elapsed if elapsed > 0 else 0

        # Clear thinking line and show stats
        if show_thinking:
            console.print(f"[dim]✓ Done: {tokens} tokens in {elapsed:.1f}s ({last_tps:.1f} t/s)[/dim]")

        info(f"Inference: {tokens} tokens in {elapsed:.1f}s ({last_tps:.1f} t/s)")

        return output.strip()

    except Exception as e:
        error(f"Inference error: {e}")
        return f"[ERROR] {e}"


def get_model_status() -> dict:
    """Get current model status."""
    loader = get_loader()
    router = get_router()
    return {
        "loaded": loader.get_loaded_model(),
        "router": router.get_status(),
        "loader": loader.get_status(),
    }
