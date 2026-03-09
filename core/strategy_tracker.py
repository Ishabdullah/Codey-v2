#!/usr/bin/env python3
"""
Strategy effectiveness tracking for Codey-v2.

Tracks which recovery strategies work best:
- Records strategy usage and outcomes
- Calculates success rates per strategy
- Recommends best strategies for error types
- Adapts based on historical performance

This makes Codey-v2's error recovery smarter over time.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

from utils.logger import info, warning, success as log_success
from core.state import get_state_store


class StrategyRecord:
    """Records a single strategy usage."""

    def __init__(self, strategy: str, error_type: str, success: bool,
                 duration: float = 0.0, context: Dict = None):
        self.strategy = strategy
        self.error_type = error_type
        self.success = success
        self.duration = duration
        self.context = context or {}
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "strategy": self.strategy,
            "error_type": self.error_type,
            "success": self.success,
            "duration": self.duration,
            "context": self.context,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "StrategyRecord":
        return cls(
            strategy=data["strategy"],
            error_type=data["error_type"],
            success=data.get("success", False),
            duration=data.get("duration", 0.0),
            context=data.get("context", {}),
        )


class StrategyStats:
    """Statistics for a single strategy."""

    def __init__(self, strategy: str):
        self.strategy = strategy
        self.total_attempts = 0
        self.successes = 0
        self.failures = 0
        self.total_duration = 0.0
        self.last_used: Optional[str] = None
        self.error_breakdown: Dict[str, int] = defaultdict(int)

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.successes / self.total_attempts

    @property
    def avg_duration(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.total_duration / self.total_attempts

    def record(self, success: bool, duration: float, error_type: str):
        self.total_attempts += 1
        if success:
            self.successes += 1
        else:
            self.failures += 1
        self.total_duration += duration
        self.last_used = datetime.now().isoformat()
        self.error_breakdown[error_type] += 1

    def to_dict(self) -> Dict:
        return {
            "strategy": self.strategy,
            "total_attempts": self.total_attempts,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": self.success_rate,
            "avg_duration": self.avg_duration,
            "last_used": self.last_used,
            "error_breakdown": dict(self.error_breakdown),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "StrategyStats":
        stats = cls(data["strategy"])
        stats.total_attempts = data["total_attempts"]
        stats.successes = data["successes"]
        stats.failures = data["failures"]
        stats.total_duration = data.get("total_duration", 0.0)
        stats.last_used = data.get("last_used")
        stats.error_breakdown = defaultdict(int, data.get("error_breakdown", {}))
        return stats


class StrategyTracker:
    """
    Tracks effectiveness of recovery strategies.

    Strategies are ranked by:
    - Success rate (primary)
    - Recent performance (weighted higher)
    - Average duration (tiebreaker)

    Provides:
    - Best strategy recommendations
    - Performance analytics
    - Adaptive strategy selection
    """

    # Built-in strategies with default configs
    BUILTIN_STRATEGIES = {
        "use_patch": {
            "description": "Use patch_file instead of write_file",
            "error_types": ["write_failed", "permission_denied"],
            "confidence": 0.9,
        },
        "create_parent_dirs": {
            "description": "Create parent directories before write",
            "error_types": ["file_not_found", "path_error"],
            "confidence": 0.95,
        },
        "install_dependency": {
            "description": "Install missing Python package",
            "error_types": ["ModuleNotFoundError", "ImportError"],
            "confidence": 0.9,
        },
        "fix_syntax": {
            "description": "Fix syntax error in code",
            "error_types": ["SyntaxError", "IndentationError"],
            "confidence": 0.8,
        },
        "fix_imports": {
            "description": "Fix import statements",
            "error_types": ["ImportError", "ModuleNotFoundError"],
            "confidence": 0.85,
        },
        "retry_with_permissions": {
            "description": "Retry command with sudo/permissions",
            "error_types": ["PermissionError", "AccessDenied"],
            "confidence": 0.7,
        },
        "search_for_solution": {
            "description": "Search for similar errors and solutions",
            "error_types": ["*"],  # Any error type
            "confidence": 0.6,
        },
        "run_single_test": {
            "description": "Run failing test in isolation",
            "error_types": ["AssertionError", "test_failure"],
            "confidence": 0.85,
        },
        "check_file_exists": {
            "description": "Verify file exists before operation",
            "error_types": ["FileNotFoundError"],
            "confidence": 0.95,
        },
        "use_absolute_path": {
            "description": "Convert relative path to absolute",
            "error_types": ["FileNotFoundError", "path_error"],
            "confidence": 0.75,
        },
    }

    def __init__(self):
        self.state = get_state_store()
        self._stats: Dict[str, StrategyStats] = {}
        self._recent_records: List[StrategyRecord] = []
        self._load_tracker()

    def _load_tracker(self):
        """Load strategy tracker from storage."""
        try:
            data = self.state.get("strategy_tracker")
            if data:
                loaded = json.loads(data)
                self._stats = {
                    key: StrategyStats.from_dict(value)
                    for key, value in loaded.items()
                }

            # Initialize built-in strategies
            for strategy in self.BUILTIN_STRATEGIES:
                if strategy not in self._stats:
                    self._stats[strategy] = StrategyStats(strategy)

        except Exception as e:
            warning(f"Failed to load strategy tracker: {e}")
            self._stats = {
                name: StrategyStats(name)
                for name in self.BUILTIN_STRATEGIES
            }

    def _save_tracker(self):
        """Save strategy tracker to storage."""
        try:
            data = {
                name: stats.to_dict()
                for name, stats in self._stats.items()
            }
            self.state.set("strategy_tracker", json.dumps(data))
        except Exception as e:
            warning(f"Failed to save strategy tracker: {e}")

    def record_attempt(self, strategy: str, error_type: str,
                       success: bool, duration: float = 0.0,
                       context: Dict = None) -> StrategyRecord:
        """
        Record a strategy attempt.

        Args:
            strategy: Strategy name used
            error_type: Type of error being fixed
            success: Whether strategy succeeded
            duration: Time taken in seconds
            context: Additional context

        Returns:
            StrategyRecord for the attempt
        """
        record = StrategyRecord(strategy, error_type, success, duration, context)
        self._recent_records.append(record)

        # Keep only last 100 records in memory
        if len(self._recent_records) > 100:
            self._recent_records = self._recent_records[-100:]

        # Update stats
        if strategy not in self._stats:
            self._stats[strategy] = StrategyStats(strategy)
        self._stats[strategy].record(success, duration, error_type)

        self._save_tracker()

        # Log result
        if success:
            log_success(f"Strategy '{strategy}' succeeded ({duration:.2f}s)")
        else:
            warning(f"Strategy '{strategy}' failed for {error_type}")

        return record

    def get_best_strategy(self, error_type: str,
                          min_attempts: int = 3) -> Optional[str]:
        """
        Get the best strategy for an error type.

        Args:
            error_type: Type of error to fix
            min_attempts: Minimum attempts for statistical significance

        Returns:
            Best strategy name or None
        """
        candidates = []

        for strategy, stats in self._stats.items():
            if stats.total_attempts < min_attempts:
                continue

            # Check if strategy is relevant for this error type
            if error_type in stats.error_breakdown:
                # Calculate weighted score
                # 70% success rate, 30% recency bonus
                score = stats.success_rate * 0.7

                # Recency bonus (used in last 7 days)
                if stats.last_used:
                    last_used = datetime.fromisoformat(stats.last_used)
                    days_ago = (datetime.now() - last_used).days
                    if days_ago <= 7:
                        score += 0.3 * (1 - days_ago / 7)

                candidates.append((strategy, score, stats.success_rate))

        if not candidates:
            # Fall back to built-in strategies
            return self._get_builtin_strategy(error_type)

        # Sort by score
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def _get_builtin_strategy(self, error_type: str) -> Optional[str]:
        """Get built-in strategy for error type."""
        for strategy, config in self.BUILTIN_STRATEGIES.items():
            if error_type in config["error_types"] or "*" in config["error_types"]:
                return strategy
        return None

    def get_strategies_for_error(self, error_type: str,
                                  limit: int = 5) -> List[Dict]:
        """
        Get ranked strategies for an error type.

        Args:
            error_type: Type of error
            limit: Maximum strategies to return

        Returns:
            List of strategy info dicts
        """
        results = []

        for strategy, stats in self._stats.items():
            if stats.total_attempts == 0:
                continue

            # Check relevance
            is_relevant = (
                error_type in stats.error_breakdown or
                self.BUILTIN_STRATEGIES.get(strategy, {}).get("error_types", []) == ["*"]
            )

            if is_relevant or stats.total_attempts >= 5:
                results.append({
                    "strategy": strategy,
                    "description": self.BUILTIN_STRATEGIES.get(
                        strategy, {}).get("description", ""),
                    "success_rate": stats.success_rate,
                    "total_attempts": stats.total_attempts,
                    "avg_duration": stats.avg_duration,
                    "relevant_for_error": is_relevant,
                })

        # Sort by success rate
        results.sort(key=lambda x: x["success_rate"], reverse=True)
        return results[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall strategy statistics."""
        total_attempts = sum(s.total_attempts for s in self._stats.values())
        total_successes = sum(s.successes for s in self._stats.values())

        # Top strategies by success rate (min 5 attempts)
        qualified = [
            (name, stats.success_rate, stats.total_attempts)
            for name, stats in self._stats.items()
            if stats.total_attempts >= 5
        ]
        qualified.sort(key=lambda x: x[1], reverse=True)

        return {
            "total_strategies": len(self._stats),
            "total_attempts": total_attempts,
            "overall_success_rate": (
                total_successes / total_attempts * 100 if total_attempts > 0 else 0
            ),
            "top_strategies": [
                {"name": name, "success_rate": rate, "attempts": attempts}
                for name, rate, attempts in qualified[:5]
            ],
            "recent_attempts": len(self._recent_records),
        }

    def reset_strategy(self, strategy: str):
        """Reset statistics for a strategy."""
        if strategy in self._stats:
            self._stats[strategy] = StrategyStats(strategy)
            self._save_tracker()
            info(f"Reset statistics for strategy '{strategy}'")

    def clear(self):
        """Clear all strategy statistics."""
        self._stats = {
            name: StrategyStats(name)
            for name in self.BUILTIN_STRATEGIES
        }
        self._recent_records = []
        self.state.delete("strategy_tracker")
        info("Strategy tracker cleared")


# Global singleton
_tracker: Optional[StrategyTracker] = None


def get_strategy_tracker() -> StrategyTracker:
    """Get the global strategy tracker."""
    global _tracker
    if _tracker is None:
        _tracker = StrategyTracker()
    return _tracker


def reset_strategy_tracker():
    """Reset strategy tracker (for testing)."""
    global _tracker
    if _tracker:
        _tracker = None
