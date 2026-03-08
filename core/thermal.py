#!/usr/bin/env python3
"""
Thermal Management for Codey v2.

Tracks inference duration and:
- Logs warning after 5 min continuous
- Reduces threads after 10 min
- Prevents thermal throttling on mobile devices

Optimized for Samsung S24 Ultra (12GB RAM, mobile CPU).
"""

import time
from typing import Optional
from pathlib import Path

from utils.logger import info, warning, error
from utils.config import THERMAL_CONFIG, MODEL_CONFIG


class ThermalManager:
    """
    Manages thermal throttling for Codey v2.
    
    Tracks:
    - Continuous inference duration
    - Total inference time
    - Thread count adjustments
    """
    
    def __init__(self):
        self._start_time: Optional[float] = None
        self._total_inference_sec: float = 0
        self._current_threads: int = MODEL_CONFIG.get("n_threads", 4)
        self._warnings_issued: int = 0
        self._thread_reductions: int = 0
        self._last_inference_end: Optional[float] = None
    
    def start_inference(self):
        """Mark the start of an inference."""
        self._start_time = time.time()
    
    def end_inference(self):
        """Mark the end of an inference and check thermal status."""
        if self._start_time is None:
            return
        
        duration = time.time() - self._start_time
        self._total_inference_sec += duration
        self._last_inference_end = time.time()
        self._start_time = None
        
        # Check if we need to throttle
        self._check_thermal_status()
    
    def _check_thermal_status(self):
        """Check thermal status and apply throttling if needed."""
        if not THERMAL_CONFIG.get("enabled", True):
            return
        
        # Check for warning threshold
        warn_after = THERMAL_CONFIG.get("warn_after_sec", 300)
        if self._total_inference_sec > warn_after:
            # Only warn once per threshold
            expected_warnings = int(self._total_inference_sec / warn_after)
            if self._warnings_issued < expected_warnings:
                warning(f"Thermal: Continuous inference for {self._total_inference_sec/60:.1f} min")
                self._warnings_issued += 1
        
        # Check for thread reduction threshold
        reduce_after = THERMAL_CONFIG.get("reduce_threads_after_sec", 600)
        if self._total_inference_sec > reduce_after:
            if self._current_threads > THERMAL_CONFIG.get("min_threads", 2):
                self._reduce_threads()
    
    def _reduce_threads(self):
        """Reduce thread count to lower thermal output."""
        old_threads = self._current_threads
        new_threads = max(
            THERMAL_CONFIG.get("min_threads", 2),
            old_threads - 2
        )
        
        if new_threads < old_threads:
            self._current_threads = new_threads
            MODEL_CONFIG["n_threads"] = new_threads
            self._thread_reductions += 1
            
            warning(
                f"Thermal: Reduced threads from {old_threads} to {new_threads} "
                f"(total inference: {self._total_inference_sec/60:.1f} min)"
            )
    
    def reset(self):
        """Reset thermal tracking (called after cooldown period)."""
        self._total_inference_sec = 0
        self._warnings_issued = 0
        self._thread_reductions = 0
        
        # Restore original thread count
        original = THERMAL_CONFIG.get("original_threads", 4)
        if self._current_threads != original:
            self._current_threads = original
            MODEL_CONFIG["n_threads"] = original
            info(f"Thermal: Restored threads to {original}")
    
    def get_status(self) -> dict:
        """Get thermal management status."""
        return {
            "total_inference_sec": round(self._total_inference_sec, 1),
            "total_inference_min": round(self._total_inference_sec / 60, 1),
            "current_threads": self._current_threads,
            "original_threads": THERMAL_CONFIG.get("original_threads", 4),
            "warnings_issued": self._warnings_issued,
            "thread_reductions": self._thread_reductions,
            "throttled": self._current_threads < THERMAL_CONFIG.get("original_threads", 4),
        }
    
    @property
    def current_threads(self) -> int:
        """Get current thread count (may be reduced due to thermal)."""
        return self._current_threads
    
    @property
    def is_throttled(self) -> bool:
        """Check if thermal throttling is active."""
        return self._current_threads < THERMAL_CONFIG.get("original_threads", 4)


# Global thermal manager instance
_thermal: Optional[ThermalManager] = None


def get_thermal_manager() -> ThermalManager:
    """Get the global thermal manager instance."""
    global _thermal
    if _thermal is None:
        _thermal = ThermalManager()
    return _thermal


def reset_thermal():
    """Reset global thermal manager (for testing)."""
    global _thermal
    if _thermal:
        _thermal = None


# Convenience functions
def start_inference():
    """Start tracking an inference."""
    get_thermal_manager().start_inference()


def end_inference():
    """End tracking an inference."""
    get_thermal_manager().end_inference()


def get_thermal_status() -> dict:
    """Get thermal status."""
    return get_thermal_manager().get_status()


def is_throttled() -> bool:
    """Check if thermal throttling is active."""
    return get_thermal_manager().is_throttled


def get_current_threads() -> int:
    """Get current thread count (may be thermally reduced)."""
    return get_thermal_manager().current_threads
