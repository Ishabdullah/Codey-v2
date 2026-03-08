#!/usr/bin/env python3
"""Inference engine for Codey v2 with dual-model support."""

import time
from utils.logger import info, error
from utils.config import MODEL_CONFIG
from core.loader_v2 import get_loader
from core.router import get_router

last_tps = 0.0

def infer(messages: list[dict], stream: bool = False, extra_stop: list = None, model: str = None) -> str:
    """Run inference with optional model selection.
    
    Args:
        messages: Chat messages in OpenAI format
        stream: Whether to stream (currently unused)
        extra_stop: Additional stop tokens
        model: 'primary' or 'secondary' (auto-routed if None)
    
    Returns:
        Model response text
    """
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
    
    # Get llama instance
    llm = loader.get_model_instance()
    if not llm:
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
    
    # Format prompt
    prompt = ""
    if system:
        prompt += f"System: {system}\n\n"
    for msg in user_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prompt += f"{role.capitalize()}: {content}\n\n"
    prompt += "Assistant:"
    
    # Run inference
    start = time.time()
    try:
        output = llm(
            prompt,
            max_tokens=MODEL_CONFIG.get("max_tokens", 1024),
            temperature=MODEL_CONFIG.get("temperature", 0.2),
            top_p=MODEL_CONFIG.get("top_p", 0.95),
            top_k=MODEL_CONFIG.get("top_k", 40),
            repeat_penalty=MODEL_CONFIG.get("repeat_penalty", 1.1),
            stop=stop,
        )
        
        elapsed = time.time() - start
        tokens = len(output.get("choices", [{}])[0].get("text", "").split())
        last_tps = tokens / elapsed if elapsed > 0 else 0
        
        info(f"Inference: {tokens} tokens in {elapsed:.1f}s ({last_tps:.1f} t/s)")
        
        return output.get("choices", [{}])[0].get("text", "").strip()
        
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
