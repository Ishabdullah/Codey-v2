#!/usr/bin/env python3
"""
Error Recovery for Codey v2.

Strategy switching on failures:
- write_file fails → try patch_file
- shell command fails → search for solution
- test fails → debug with targeted fixes
- import error → suggest installation

Adapts like a human developer would.
"""

from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass
from enum import Enum

from utils.logger import info, warning, error, success


class ErrorType(Enum):
    """Types of errors that can occur."""
    FILE_WRITE = "file_write"
    FILE_NOT_FOUND = "file_not_found"
    SHELL_ERROR = "shell_error"
    IMPORT_ERROR = "import_error"
    SYNTAX_ERROR = "syntax_error"
    TEST_FAILURE = "test_failure"
    PERMISSION_ERROR = "permission_error"
    UNKNOWN = "unknown"


@dataclass
class FallbackStrategy:
    """A fallback strategy for error recovery."""
    name: str
    description: str
    action: str  # The action to take
    confidence: float  # 0.0 to 1.0


class StrategySwitcher:
    """
    Switches strategies on failure.
    
    Instead of fixed retry count, adapts approach:
    - write_file fails → try patch_file
    - shell fails → search for solution
    - test fails → debug with targeted fixes
    """
    
    def __init__(self):
        self._fallback_trees: Dict[ErrorType, List[FallbackStrategy]] = {}
        self._error_history: List[Dict] = []
        self._max_retries = 3
        
        # Register default fallback trees
        self._register_default_fallbacks()
    
    def _register_default_fallbacks(self):
        """Register default fallback strategies."""
        
        # File write failures
        self._fallback_trees[ErrorType.FILE_WRITE] = [
            FallbackStrategy(
                name="use_patch",
                description="Use patch instead of full write",
                action="patch_file",
                confidence=0.9
            ),
            FallbackStrategy(
                name="create_parent_dirs",
                description="Create parent directories first",
                action="mkdir_then_write",
                confidence=0.8
            ),
            FallbackStrategy(
                name="check_permissions",
                description="Check file permissions",
                action="check_and_fix_permissions",
                confidence=0.7
            ),
        ]
        
        # File not found
        self._fallback_trees[ErrorType.FILE_NOT_FOUND] = [
            FallbackStrategy(
                name="create_file",
                description="Create the file first",
                action="create_then_modify",
                confidence=0.95
            ),
            FallbackStrategy(
                name="search_similar",
                description="Search for similar files",
                action="search_files",
                confidence=0.6
            ),
        ]
        
        # Shell command errors
        self._fallback_trees[ErrorType.SHELL_ERROR] = [
            FallbackStrategy(
                name="search_error",
                description="Search for error solution",
                action="search_error_message",
                confidence=0.8
            ),
            FallbackStrategy(
                name="try_alternative",
                description="Try alternative command",
                action="alternative_command",
                confidence=0.7
            ),
            FallbackStrategy(
                name="check_dependencies",
                description="Check if required tools installed",
                action="verify_dependencies",
                confidence=0.75
            ),
        ]
        
        # Import errors
        self._fallback_trees[ErrorType.IMPORT_ERROR] = [
            FallbackStrategy(
                name="install_package",
                description="Install missing package",
                action="pip_install",
                confidence=0.9
            ),
            FallbackStrategy(
                name="check_venv",
                description="Check virtual environment",
                action="verify_environment",
                confidence=0.7
            ),
        ]
        
        # Syntax errors
        self._fallback_trees[ErrorType.SYNTAX_ERROR] = [
            FallbackStrategy(
                name="fix_syntax",
                description="Fix syntax error",
                action="correct_syntax",
                confidence=0.85
            ),
            FallbackStrategy(
                name="minimal_test",
                description="Test with minimal code",
                action="isolate_and_test",
                confidence=0.75
            ),
        ]
        
        # Test failures
        self._fallback_trees[ErrorType.TEST_FAILURE] = [
            FallbackStrategy(
                name="debug_test",
                description="Debug failing test",
                action="run_with_debug",
                confidence=0.85
            ),
            FallbackStrategy(
                name="check_assertions",
                description="Check test assertions",
                action="verify_assertions",
                confidence=0.75
            ),
            FallbackStrategy(
                name="isolate_failure",
                description="Isolate failing test case",
                action="run_single_test",
                confidence=0.8
            ),
        ]
        
        # Permission errors
        self._fallback_trees[ErrorType.PERMISSION_ERROR] = [
            FallbackStrategy(
                name="fix_permissions",
                description="Fix file permissions",
                action="chmod_fix",
                confidence=0.85
            ),
            FallbackStrategy(
                name="use_sudo",
                description="Run with elevated privileges",
                action="sudo_command",
                confidence=0.6
            ),
            FallbackStrategy(
                name="change_location",
                description="Write to different location",
                action="write_elsewhere",
                confidence=0.7
            ),
        ]
    
    def classify_error(self, error_message: str) -> ErrorType:
        """
        Classify an error message into an ErrorType.
        
        Args:
            error_message: The error message to classify
            
        Returns:
            The classified ErrorType
        """
        error_lower = error_message.lower()
        
        # File-related errors
        if "write" in error_lower and ("fail" in error_lower or "error" in error_lower):
            return ErrorType.FILE_WRITE
        if "not found" in error_lower or "no such file" in error_lower:
            return ErrorType.FILE_NOT_FOUND
        if "permission" in error_lower or "access denied" in error_lower:
            return ErrorType.PERMISSION_ERROR
        
        # Shell errors
        if "command not found" in error_lower:
            return ErrorType.SHELL_ERROR
        if "exit code" in error_lower or "returned non-zero" in error_lower:
            return ErrorType.SHELL_ERROR
        
        # Python errors
        if "importerror" in error_lower or "modulenotfound" in error_lower:
            return ErrorType.IMPORT_ERROR
        if "syntaxerror" in error_lower or "invalid syntax" in error_lower:
            return ErrorType.SYNTAX_ERROR
        if "assertionerror" in error_lower or "test failed" in error_lower:
            return ErrorType.TEST_FAILURE
        
        return ErrorType.UNKNOWN
    
    def get_fallback(self, error_type: ErrorType = None, 
                     error_message: str = None) -> Optional[FallbackStrategy]:
        """
        Get the best fallback strategy for an error.
        
        Args:
            error_type: The type of error (optional)
            error_message: Error message to classify (optional)
            
        Returns:
            Best fallback strategy, or None
        """
        # Classify error if only message provided
        if error_type is None and error_message:
            error_type = self.classify_error(error_message)
        
        if error_type is None:
            return None
        
        # Get fallback tree for this error type
        fallbacks = self._fallback_trees.get(error_type, [])
        
        if not fallbacks:
            # Return generic fallback for unknown errors
            return FallbackStrategy(
                name="manual_review",
                description="Manual review required",
                action="log_and_continue",
                confidence=0.5
            )
        
        # Return highest confidence fallback
        return max(fallbacks, key=lambda f: f.confidence)
    
    def get_all_fallbacks(self, error_type: ErrorType) -> List[FallbackStrategy]:
        """Get all fallback strategies for an error type, ordered by confidence."""
        fallbacks = self._fallback_trees.get(error_type, [])
        return sorted(fallbacks, key=lambda f: f.confidence, reverse=True)
    
    def record_error(self, error_type: ErrorType, error_message: str, 
                     strategy_used: str, success: bool):
        """
        Record an error and recovery attempt.
        
        Args:
            error_type: Type of error
            error_message: Original error message
            strategy_used: Strategy that was attempted
            success: Whether recovery succeeded
        """
        self._error_history.append({
            "error_type": error_type.value,
            "error_message": error_message[:200],
            "strategy": strategy_used,
            "success": success,
        })
        
        # Trim history
        if len(self._error_history) > 100:
            self._error_history = self._error_history[-100:]
    
    def get_success_rate(self, strategy_name: str) -> float:
        """
        Get success rate for a strategy.
        
        Args:
            strategy_name: Name of the strategy
            
        Returns:
            Success rate (0.0 to 1.0)
        """
        attempts = [e for e in self._error_history if e["strategy"] == strategy_name]
        if not attempts:
            return 0.5  # Default
        
        successes = sum(1 for e in attempts if e["success"])
        return successes / len(attempts)
    
    def adapt_strategy(self, error_type: ErrorType, 
                       failed_strategy: str) -> Optional[FallbackStrategy]:
        """
        Adapt strategy after a failure.
        
        Tries the next best strategy that hasn't been tried.
        
        Args:
            error_type: Type of error
            failed_strategy: Strategy that just failed
            
        Returns:
            Next best strategy, or None
        """
        fallbacks = self.get_all_fallbacks(error_type)
        
        # Filter out failed strategy
        remaining = [f for f in fallbacks if f.name != failed_strategy]
        
        # Adjust confidence based on historical success rate
        for f in remaining:
            rate = self.get_success_rate(f.name)
            f.confidence *= rate  # Reduce confidence if low success rate
        
        if remaining:
            return max(remaining, key=lambda f: f.confidence)
        
        return None
    
    def get_error_summary(self) -> Dict:
        """Get summary of error history."""
        if not self._error_history:
            return {"total": 0}
        
        # Count by type
        by_type = {}
        for e in self._error_history:
            t = e["error_type"]
            by_type[t] = by_type.get(t, 0) + 1
        
        # Count successes
        successes = sum(1 for e in self._error_history if e["success"])
        
        return {
            "total": len(self._error_history),
            "successes": successes,
            "failures": len(self._error_history) - successes,
            "success_rate": successes / len(self._error_history),
            "by_type": by_type,
        }


# Global switcher instance
_switcher: Optional[StrategySwitcher] = None


def get_switcher() -> StrategySwitcher:
    """Get the global strategy switcher instance."""
    global _switcher
    if _switcher is None:
        _switcher = StrategySwitcher()
    return _switcher


def reset_switcher():
    """Reset global switcher (for testing)."""
    global _switcher
    if _switcher:
        _switcher = None


def recover_from_error(error_message: str) -> Optional[FallbackStrategy]:
    """
    Convenience function to get fallback for an error.
    
    Args:
        error_message: Error message to recover from
        
    Returns:
        Suggested fallback strategy
    """
    return get_switcher().get_fallback(error_message=error_message)
