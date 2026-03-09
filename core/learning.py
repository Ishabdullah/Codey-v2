#!/usr/bin/env python3
"""
Learning manager for Codey-v2.

Integrates:
- User preference learning
- Error pattern database
- Strategy effectiveness tracking

Provides unified interface for Codey-v2 to learn and improve over time.
"""

import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from utils.logger import info, warning, success as log_success
from core.preferences import get_preferences, PreferenceManager
from core.error_database import get_error_database, ErrorDatabase
from core.strategy_tracker import get_strategy_tracker, StrategyTracker


class LearningManager:
    """
    Unified learning manager for Codey-v2.

    Coordinates learning across:
    - Preferences (user style)
    - Errors (what went wrong + fixes)
    - Strategies (what recovery approaches work)

    Usage:
        learning = get_learning_manager()

        # Learn from file
        learning.learn_from_file("test_auth.py", content)

        # Record error and fix
        learning.record_error("ModuleNotFoundError", "...", fix="pip install flask")

        # Get best strategy
        strategy = learning.get_best_strategy("ModuleNotFoundError")

        # Get user preferences
        test_framework = learning.get_preference("test_framework")
    """

    def __init__(self):
        self.preferences: PreferenceManager = get_preferences()
        self.error_db: ErrorDatabase = get_error_database()
        self.strategy_tracker: StrategyTracker = get_strategy_tracker()

    def learn_from_file(self, path: str, content: str) -> Dict[str, str]:
        """
        Learn preferences from a file.

        Args:
            path: File path
            content: File content

        Returns:
            Detected preferences
        """
        return self.preferences.learn_from_file(path, content)

    def learn_from_files(self, files: List[tuple]) -> Dict[str, List[str]]:
        """
        Learn preferences from multiple files.

        Args:
            files: List of (path, content) tuples

        Returns:
            All detected preferences
        """
        return self.preferences.learn_from_files(files)

    def record_error(self, error_type: str, error_message: str,
                     context: Dict = None) -> str:
        """
        Record an error occurrence.

        Args:
            error_type: Type of error
            error_message: Error message
            context: Additional context

        Returns:
            Error pattern key
        """
        return self.error_db.record_error(error_type, error_message, context)

    def record_fix(self, error_key: str, fix: str, success: bool = True):
        """
        Record a fix for an error.

        Args:
            error_key: Error pattern key
            fix: Fix description
            success: Whether fix worked
        """
        self.error_db.record_fix(error_key, fix, success)

    def record_strategy_attempt(self, strategy: str, error_type: str,
                                 success: bool, duration: float = 0.0):
        """
        Record a strategy attempt.

        Args:
            strategy: Strategy name
            error_type: Type of error
            success: Whether strategy succeeded
            duration: Time taken in seconds
        """
        self.strategy_tracker.record_attempt(
            strategy, error_type, success, duration
        )

    def learn_from_error_and_fix(self, error_type: str, error_message: str,
                                  fix: str, success: bool = True,
                                  strategy: str = None,
                                  duration: float = 0.0,
                                  context: Dict = None):
        """
        Learn from a complete error-fix cycle.

        Args:
            error_type: Type of error
            error_message: Error message
            fix: Fix that was applied
            success: Whether fix worked
            strategy: Strategy name (if applicable)
            duration: Time taken
            context: Additional context
        """
        # Record in error database
        error_key = self.error_db.record_error(error_type, error_message, context)
        self.error_db.record_fix(error_key, fix, success)

        # Record strategy effectiveness
        if strategy:
            self.strategy_tracker.record_attempt(
                strategy, error_type, success, duration
            )

        if success:
            log_success(f"Learned from {error_type}: {fix[:50]}...")
        else:
            warning(f"Failed fix for {error_type}: {fix[:50]}...")

    def get_best_strategy(self, error_type: str) -> Optional[str]:
        """
        Get the best strategy for an error type.

        Args:
            error_type: Type of error

        Returns:
            Best strategy name or None
        """
        return self.strategy_tracker.get_best_strategy(error_type)

    def suggest_fix(self, error_type: str, error_message: str) -> Optional[str]:
        """
        Suggest a fix for an error.

        Args:
            error_type: Type of error
            error_message: Error message

        Returns:
            Suggested fix or None
        """
        return self.error_db.suggest_fix(error_type, error_message)

    def get_preference(self, category: str, default: str = None) -> Optional[str]:
        """
        Get a user preference.

        Args:
            category: Preference category
            default: Default value

        Returns:
            Preferred value or default
        """
        return self.preferences.get(category, default)

    def get_all_preferences(self) -> Dict[str, str]:
        """Get all learned preferences."""
        return self.preferences.get_all()

    def get_similar_errors(self, error_type: str, error_message: str,
                           limit: int = 5) -> List:
        """
        Find similar errors and their fixes.

        Args:
            error_type: Type of error
            error_message: Error message
            limit: Maximum results

        Returns:
            List of (pattern, similarity) tuples
        """
        return self.error_db.find_similar_errors(error_type, error_message, limit)

    def get_status(self) -> Dict[str, Any]:
        """Get learning system status."""
        return {
            "preferences": self.preferences.status(),
            "errors": self.error_db.get_statistics(),
            "strategies": self.strategy_tracker.get_statistics(),
        }

    def clear_all(self):
        """Clear all learned data."""
        self.preferences.clear()
        self.error_db.clear()
        self.strategy_tracker.clear()
        info("All learning data cleared")


# Global singleton
_learning: Optional[LearningManager] = None


def get_learning_manager() -> LearningManager:
    """Get the global learning manager."""
    global _learning
    if _learning is None:
        _learning = LearningManager()
    return _learning


def reset_learning_manager():
    """Reset learning manager (for testing)."""
    global _learning
    if _learning:
        _learning = None
