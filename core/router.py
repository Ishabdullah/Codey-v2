#!/usr/bin/env python3
"""
Model router for Codey-v2.

Routes tasks to appropriate model based on complexity:
- Simple tasks (<50 chars, simple keywords) → 1.5B model
- Complex tasks → 7B model

Implements cooldown to prevent model thrashing.
"""

import time
from typing import Literal
from pathlib import Path

from utils.config import ROUTER_CONFIG, MODEL_PATH, SECONDARY_MODEL_PATH


ModelType = Literal["primary", "secondary"]


class ModelRouter:
    """
    Routes tasks to appropriate model.
    
    Uses heuristic-based routing:
    - Short input + simple keywords → secondary (1.5B)
    - Everything else → primary (7B)
    
    Implements cooldown to prevent rapid swapping.
    """
    
    def __init__(self):
        self._last_swap_time: float = 0
        self._current_model: ModelType = "primary"
        self._swap_count: int = 0
    
    def route_task(self, user_input: str) -> ModelType:
        """
        Determine which model should handle a task.
        
        Args:
            user_input: The user's prompt/input
            
        Returns:
            "primary" for 7B model, "secondary" for 1.5B model
        """
        # Check if we're in cooldown period
        now = time.time()
        time_since_swap = now - self._last_swap_time
        
        # If in cooldown, stick with current model
        if time_since_swap < ROUTER_CONFIG["swap_cooldown_sec"]:
            return self._current_model
        
        # Analyze input complexity
        is_simple = self._is_simple_task(user_input)
        
        if is_simple:
            target_model = "secondary"
        else:
            target_model = "primary"
        
        # Track swap
        if target_model != self._current_model:
            self._last_swap_time = now
            self._swap_count += 1
        
        self._current_model = target_model
        return target_model
    
    def _is_simple_task(self, user_input: str) -> bool:
        """
        Determine if a task is simple enough for the 1.5B model.
        
        Criteria:
        - Length < simple_max_chars
        - Contains simple keywords (greeting, thanks, etc.)
        - No complex instructions (no "create", "implement", "fix", etc.)
        """
        text = user_input.strip().lower()
        
        # Check length
        if len(text) > ROUTER_CONFIG["simple_max_chars"]:
            return False
        
        # Check for simple keywords
        for keyword in ROUTER_CONFIG["simple_keywords"]:
            if keyword in text:
                return True
        
        # Check for complex indicators (should use primary)
        complex_indicators = [
            "create", "implement", "build", "write a", "make a",
            "fix", "debug", "error", "bug",
            "function", "class", "module",
            "test", "refactor", "optimize",
            "explain", "analyze", "review",
        ]
        
        for indicator in complex_indicators:
            if indicator in text:
                return False
        
        # Short input without complex indicators → simple
        return len(text) < 30
    
    def get_current_model(self) -> ModelType:
        """Get the currently selected model."""
        return self._current_model
    
    def get_swap_count(self) -> int:
        """Get total number of model swaps."""
        return self._swap_count
    
    def get_time_since_swap(self) -> float:
        """Get seconds since last model swap."""
        return time.time() - self._last_swap_time
    
    def force_model(self, model: ModelType):
        """Force a specific model (bypasses routing)."""
        self._current_model = model
        self._last_swap_time = time.time()
    
    def get_model_path(self, model: ModelType = None) -> Path:
        """Get the path to the model file."""
        if model is None:
            model = self._current_model
        
        if model == "primary":
            return MODEL_PATH
        else:
            return SECONDARY_MODEL_PATH
    
    def get_status(self) -> dict:
        """Get router status."""
        return {
            "current_model": self._current_model,
            "swap_count": self._swap_count,
            "time_since_swap": round(self.get_time_since_swap(), 1),
            "cooldown_remaining": max(0, ROUTER_CONFIG["swap_cooldown_sec"] - self.get_time_since_swap()),
        }


# Global router instance
_router: ModelRouter = None


def get_router() -> ModelRouter:
    """Get the global router instance."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def route_task(user_input: str) -> ModelType:
    """Route a task to appropriate model."""
    return get_router().route_task(user_input)


def reset_router():
    """Reset the global router (for testing)."""
    global _router
    if _router:
        _router = None
