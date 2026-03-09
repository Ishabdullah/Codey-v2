#!/usr/bin/env python3
"""
Observability for Codey-v2.

Agent can query its own state:
- Token usage
- Memory contents
- Task queue status
- Model loaded
- Thermal status
- Health metrics

Exposed via /status CLI command and agent-internal queries.
"""

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

# psutil is optional - will use fallback if not available
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from utils.logger import info, warning
from utils.config import MODEL_CONFIG, CODEY_VERSION
from core.state import get_state_store


class State:
    """
    Observable state for Codey-v2.

    Provides property accessors for:
    - tokens_used
    - memory_loaded
    - tasks_pending
    - model_active
    - temperature
    - health metrics
    """
    
    def __init__(self):
        self.state_store = get_state_store()
        if HAS_PSUTIL:
            self._process = psutil.Process(os.getpid())
        else:
            self._process = None
    
    @property
    def tokens_used(self) -> int:
        """Get total tokens used (from state)."""
        return int(self.state_store.get("tokens_used", 0))
    
    @tokens_used.setter
    def tokens_used(self, value: int):
        """Set total tokens used."""
        self.state_store.set("tokens_used", value)
    
    @property
    def memory_loaded(self) -> Dict:
        """Get memory status."""
        try:
            from core.memory_v2 import get_memory
            memory = get_memory()
            return memory.status()
        except:
            return {"error": "Memory not initialized"}
    
    @property
    def tasks_pending(self) -> int:
        """Get number of pending tasks."""
        try:
            from core.planner_v2 import get_planner
            planner = get_planner()
            return len(planner.get_pending_tasks())
        except:
            # Fallback to state store
            tasks = self.state_store.get_tasks_by_status("pending")
            return len(tasks)
    
    @property
    def tasks_running(self) -> int:
        """Get number of running tasks."""
        try:
            from core.planner_v2 import get_planner
            planner = get_planner()
            return len(planner.get_running_tasks())
        except:
            tasks = self.state_store.get_tasks_by_status("running")
            return len(tasks)
    
    @property
    def model_active(self) -> Optional[str]:
        """Get currently active model."""
        try:
            from core.loader_v2 import get_loader
            loader = get_loader()
            return loader.get_loaded_model()
        except:
            return None
    
    @property
    def model_state(self) -> Dict:
        """Get model state from database."""
        return self.state_store.get_model_state()
    
    @property
    def temperature(self) -> float:
        """Get current temperature (from model config)."""
        return MODEL_CONFIG.get("temperature", 0.2)
    
    @property
    def context_size(self) -> int:
        """Get context size (from model config)."""
        return MODEL_CONFIG.get("n_ctx", 4096)
    
    @property
    def memory_usage(self) -> Dict:
        """Get process memory usage."""
        if HAS_PSUTIL and self._process:
            try:
                mem_info = self._process.memory_info()
                return {
                    "rss_mb": round(mem_info.rss / 1024 / 1024, 1),
                    "vms_mb": round(mem_info.vms / 1024 / 1024, 1),
                }
            except:
                pass
        # Fallback: read from /proc on Linux
        try:
            with open(f"/proc/{os.getpid()}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        return {"rss_mb": round(rss_kb / 1024, 1), "vms_mb": 0}
        except:
            pass
        return {"rss_mb": 0, "vms_mb": 0}
    
    @property
    def cpu_usage(self) -> float:
        """Get CPU usage percentage."""
        if HAS_PSUTIL and self._process:
            try:
                return round(self._process.cpu_percent(interval=0.1), 1)
            except:
                pass
        return 0.0
    
    @property
    def uptime(self) -> int:
        """Get daemon uptime in seconds."""
        started_at = int(self.state_store.get("daemon_started_at", 0))
        if started_at:
            return int(time.time()) - started_at
        return 0
    
    @property
    def daemon_pid(self) -> Optional[int]:
        """Get daemon PID."""
        try:
            return self._process.pid
        except:
            return None
    
    @property
    def health(self) -> Dict:
        """Get health metrics."""
        return {
            "memory_usage": self.memory_usage,
            "cpu_usage": self.cpu_usage,
            "uptime_seconds": self.uptime,
            "tasks_pending": self.tasks_pending,
            "model_loaded": self.model_active is not None,
        }
    
    def get_full_status(self) -> Dict:
        """Get complete observability status."""
        return {
            "version": CODEY_VERSION,
            "daemon": {
                "pid": self.daemon_pid,
                "uptime_seconds": self.uptime,
            },
            "model": {
                "active": self.model_active,
                "temperature": self.temperature,
                "context_size": self.context_size,
                "state": self.model_state,
            },
            "tasks": {
                "pending": self.tasks_pending,
                "running": self.tasks_running,
            },
            "memory": {
                "usage": self.memory_usage,
                "loaded": self.memory_loaded,
            },
            "cpu": {
                "usage": self.cpu_usage,
            },
            "tokens": {
                "used": self.tokens_used,
            },
            "health": self.health,
        }
    
    def to_dict(self) -> Dict:
        """Alias for get_full_status()."""
        return self.get_full_status()


# Global state instance
_state: Optional[State] = None


def get_state() -> State:
    """Get the global state instance."""
    global _state
    if _state is None:
        _state = State()
    return _state


def reset_state():
    """Reset global state (for testing)."""
    global _state
    if _state:
        _state = None


def status() -> Dict:
    """Get current status (convenience function)."""
    return get_state().get_full_status()
