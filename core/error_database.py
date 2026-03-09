#!/usr/bin/env python3
"""
Error pattern database for Codey-v2.

Learns from errors and their successful fixes:
- Records errors encountered
- Tracks which fixes worked
- Suggests fixes for similar errors
- Builds a knowledge base over time

This makes Codey-v2 genuinely smarter with each error fixed.
"""

import json
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from collections import defaultdict

from utils.logger import info, warning, success
from core.state import get_state_store


class ErrorPattern:
    """Represents a learned error pattern."""

    def __init__(self, error_type: str, error_message: str, fix: str,
                 success: bool, context: Dict = None):
        self.error_type = error_type
        self.error_message = error_message
        self.fix = fix
        self.success = success
        self.context = context or {}
        self.created_at = datetime.now().isoformat()
        self.times_seen = 1
        self.times_fixed = 1 if success else 0

    def to_dict(self) -> Dict:
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "fix": self.fix,
            "success": self.success,
            "context": self.context,
            "created_at": self.created_at,
            "times_seen": self.times_seen,
            "times_fixed": self.times_fixed,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ErrorPattern":
        pattern = cls(
            error_type=data["error_type"],
            error_message=data["error_message"],
            fix=data.get("fix", ""),
            success=data.get("success", False),
            context=data.get("context", {}),
        )
        pattern.created_at = data.get("created_at", pattern.created_at)
        pattern.times_seen = data.get("times_seen", 1)
        pattern.times_fixed = data.get("times_fixed", 0)
        return pattern

    def similarity_score(self, other: "ErrorPattern") -> float:
        """Calculate similarity to another error pattern."""
        score = 0.0

        # Same error type is strong signal
        if self.error_type == other.error_type:
            score += 0.4

        # Similar error messages
        msg_similarity = self._string_similarity(
            self.error_message.lower(),
            other.error_message.lower()
        )
        score += msg_similarity * 0.4

        # Same file type context
        if self.context.get("file_ext") == other.context.get("file_ext"):
            score += 0.2

        return min(1.0, score)

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Simple string similarity using common words."""
        words1 = set(re.findall(r'\w+', s1))
        words2 = set(re.findall(r'\w+', s2))
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union) if union else 0.0


class ErrorDatabase:
    """
    Database of error patterns and their fixes.

    Automatically learns from:
    - Errors encountered during execution
    - Fixes that resolved the error
    - User-provided solutions

    Provides:
    - Similar error lookup
    - Fix suggestions
    - Error frequency analysis
    """

    # Error type categorization
    ERROR_CATEGORIES = {
        "ModuleNotFoundError": "import",
        "ImportError": "import",
        "SyntaxError": "syntax",
        "IndentationError": "syntax",
        "NameError": "name_reference",
        "TypeError": "type",
        "ValueError": "value",
        "AttributeError": "attribute",
        "KeyError": "key_access",
        "IndexError": "index_access",
        "FileNotFoundError": "file_io",
        "PermissionError": "file_io",
        "TimeoutError": "timeout",
        "ConnectionError": "network",
        "HTTPError": "network",
        "AssertionError": "test_failure",
        "pytest": "test_failure",
        "unittest": "test_failure",
    }

    # Common fix patterns
    FIX_PATTERNS = {
        "import": [
            ("ModuleNotFoundError", "pip install {module}"),
            ("ImportError", "Check import path or install package"),
        ],
        "syntax": [
            ("SyntaxError", "Check line {line} for syntax issues"),
            ("IndentationError", "Fix indentation at line {line}"),
        ],
        "file_io": [
            ("FileNotFoundError", "Create file or check path"),
            ("PermissionError", "chmod +x or check permissions"),
        ],
    }

    def __init__(self):
        self.state = get_state_store()
        self._cache: Dict[str, ErrorPattern] = {}
        self._load_database()

    def _load_database(self):
        """Load error database from storage."""
        try:
            data = self.state.get("error_database")
            if data:
                loaded = json.loads(data)
                self._cache = {
                    key: ErrorPattern.from_dict(value)
                    for key, value in loaded.items()
                }
        except Exception as e:
            warning(f"Failed to load error database: {e}")
            self._cache = {}

    def _save_database(self):
        """Save error database to storage."""
        try:
            data = {
                key: pattern.to_dict()
                for key, pattern in self._cache.items()
            }
            self.state.set("error_database", json.dumps(data))
        except Exception as e:
            warning(f"Failed to save error database: {e}")

    def _generate_key(self, error_type: str, error_message: str) -> str:
        """Generate unique key for error pattern."""
        # Normalize error message (remove specific paths, line numbers)
        normalized = re.sub(r'line \d+', 'line N', error_message.lower())
        normalized = re.sub(r'file "[^"]+"', 'file "..."', normalized)
        normalized = re.sub(r'/[a-zA-Z0-9_/.-]+', '/...', normalized)

        content = f"{error_type}:{normalized}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def record_error(self, error_type: str, error_message: str,
                     context: Dict = None) -> str:
        """
        Record an error occurrence.

        Args:
            error_type: Type of error (e.g., "ModuleNotFoundError")
            error_message: Full error message
            context: Additional context (file, line, code snippet)

        Returns:
            Error pattern key
        """
        key = self._generate_key(error_type, error_message)

        if key in self._cache:
            # Increment seen count
            self._cache[key].times_seen += 1
        else:
            # New error pattern
            self._cache[key] = ErrorPattern(
                error_type=error_type,
                error_message=error_message,
                fix="",
                success=False,
                context=context or {},
            )

        self._save_database()
        return key

    def record_fix(self, error_key: str, fix: str, success: bool = True):
        """
        Record a fix for an error.

        Args:
            error_key: Error pattern key from record_error
            fix: Description of fix applied
            success: Whether fix resolved the issue
        """
        if error_key not in self._cache:
            warning(f"Error key {error_key} not found")
            return

        pattern = self._cache[error_key]
        pattern.fix = fix
        pattern.success = success
        if success:
            pattern.times_fixed += 1

        self._save_database()
        info(f"Recorded fix for {pattern.error_type}: {fix[:50]}...")

    def learn_from_error(self, error_type: str, error_message: str,
                         fix: str, success: bool = True,
                         context: Dict = None):
        """
        Learn from an error and its fix in one call.

        Args:
            error_type: Type of error
            error_message: Full error message
            fix: Fix that was applied
            success: Whether fix worked
            context: Additional context
        """
        key = self.record_error(error_type, error_message, context)
        self.record_fix(key, fix, success)

    def find_similar_errors(self, error_type: str, error_message: str,
                            limit: int = 5) -> List[Tuple[ErrorPattern, float]]:
        """
        Find similar error patterns.

        Args:
            error_type: Type of error to match
            error_message: Error message to match
            limit: Maximum results to return

        Returns:
            List of (pattern, similarity_score) tuples
        """
        query = ErrorPattern(error_type, error_message, "", False)
        results = []

        for pattern in self._cache.values():
            score = query.similarity_score(pattern)
            if score > 0.3:  # Minimum similarity threshold
                results.append((pattern, score))

        # Sort by similarity
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def suggest_fix(self, error_type: str, error_message: str) -> Optional[str]:
        """
        Suggest a fix for an error.

        Args:
            error_type: Type of error
            error_message: Full error message

        Returns:
            Suggested fix or None
        """
        # First, check learned fixes
        similar = self.find_similar_errors(error_type, error_message, limit=3)
        for pattern, score in similar:
            if pattern.success and pattern.fix:
                info(f"Using learned fix (similarity: {score:.2f})")
                return pattern.fix

        # Fallback: use fix patterns
        category = self.ERROR_CATEGORIES.get(error_type, "unknown")
        if category in self.FIX_PATTERNS:
            for err_pattern, fix_template in self.FIX_PATTERNS[category]:
                if err_pattern in error_type or err_pattern in error_message:
                    # Extract context for template
                    context = {
                        "module": self._extract_module(error_message),
                        "line": self._extract_line(error_message),
                    }
                    return fix_template.format(**context)

        return None

    def _extract_module(self, error_message: str) -> str:
        """Extract module name from error message."""
        match = re.search(r"No module named ['\"]?(\w+)['\"]?", error_message)
        return match.group(1) if match else "unknown"

    def _extract_line(self, error_message: str) -> str:
        """Extract line number from error message."""
        match = re.search(r'line (\d+)', error_message)
        return match.group(1) if match else "N"

    def get_statistics(self) -> Dict[str, Any]:
        """Get error database statistics."""
        total_errors = len(self._cache)
        total_seen = sum(p.times_seen for p in self._cache.values())
        total_fixed = sum(p.times_fixed for p in self._cache.values())

        # Group by error type
        by_type = defaultdict(int)
        for pattern in self._cache.values():
            by_type[pattern.error_type] += pattern.times_seen

        # Success rate
        success_rate = (total_fixed / total_seen * 100) if total_seen > 0 else 0

        return {
            "total_patterns": total_errors,
            "total_occurrences": total_seen,
            "total_fixed": total_fixed,
            "success_rate": f"{success_rate:.1f}%",
            "by_type": dict(by_type),
            "most_common": max(by_type.items(), key=lambda x: x[1])[0] if by_type else None,
        }

    def clear(self):
        """Clear error database."""
        self._cache = {}
        self.state.delete("error_database")
        info("Error database cleared")


# Global singleton
_error_db: Optional[ErrorDatabase] = None


def get_error_database() -> ErrorDatabase:
    """Get the global error database."""
    global _error_db
    if _error_db is None:
        _error_db = ErrorDatabase()
    return _error_db


def reset_error_database():
    """Reset error database (for testing)."""
    global _error_db
    if _error_db:
        _error_db = None
