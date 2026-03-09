#!/usr/bin/env python3
"""
User preference learning for Codey-v2.

Automatically learns and remembers user preferences:
- Test framework (pytest vs unittest)
- Code style (black, pep8, etc.)
- Naming conventions
- Import style
- Common patterns

Preferences are stored in SQLite and improve over time.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict

from utils.logger import info, warning
from core.state import get_state_store


class PreferenceDetector:
    """Detects user preferences from code analysis."""

    # Test framework patterns
    TEST_FRAMEWORKS = {
        "pytest": [
            r"import pytest",
            r"from pytest import",
            r"def test_\w+\(",
            r"@pytest\.fixture",
            r"assert\s+\w+\s+(?:==|in|is|is not)",
        ],
        "unittest": [
            r"import unittest",
            r"from unittest import",
            r"class \w+Test\(unittest\.TestCase\)",
            r"def test_\w+\(self\)",
            r"self\.assert(?:Equal|True|False|IsNone|IsNotNone)",
        ],
        "nose": [
            r"import nose",
            r"from nose import",
            r"nose\.tools",
        ],
    }

    # Code style patterns
    CODE_STYLES = {
        "black": [
            r'"\w+"',  # Black prefers double quotes
            r"\(\w+, \w+\)",  # Trailing commas
        ],
        "pep8": [
            r"# type: ",  # Type comments
            r"#: ",  # Sphinx-style comments
        ],
    }

    # Naming conventions
    NAMING_PATTERNS = {
        "snake_case": r"def [a-z][a-z0-9_]*\(",
        "camelCase": r"def [a-z][a-zA-Z0-9]*\(",
        "PascalCase": r"class [A-Z][a-zA-Z0-9]*:",
    }

    # Import styles
    IMPORT_STYLES = {
        "absolute": r"^import \w+",
        "relative": r"^from \.\.?\w+ import",
        "aliased": r"import \w+ as \w+",
    }

    @classmethod
    def detect_test_framework(cls, content: str) -> Optional[str]:
        """Detect test framework from file content."""
        scores = defaultdict(int)
        for framework, patterns in cls.TEST_FRAMEWORKS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.MULTILINE):
                    scores[framework] += 1
        return max(scores, key=scores.get) if scores else None

    @classmethod
    def detect_code_style(cls, content: str) -> Optional[str]:
        """Detect code style from file content."""
        scores = defaultdict(int)
        for style, patterns in cls.CODE_STYLES.items():
            for pattern in patterns:
                if re.search(pattern, content, re.MULTILINE):
                    scores[style] += 1
        return max(scores, key=scores.get) if scores else None

    @classmethod
    def detect_naming_convention(cls, content: str) -> Optional[str]:
        """Detect naming convention from file content."""
        matches = {}
        for convention, pattern in cls.NAMING_PATTERNS.items():
            count = len(re.findall(pattern, content))
            if count > 0:
                matches[convention] = count
        return max(matches, key=matches.get) if matches else None

    @classmethod
    def detect_import_style(cls, content: str) -> Optional[str]:
        """Detect import style from file content."""
        scores = defaultdict(int)
        for style, pattern in cls.IMPORT_STYLES.items():
            matches = re.findall(pattern, content, re.MULTILINE)
            scores[style] = len(matches)
        return max(scores, key=scores.get) if scores else None

    @classmethod
    def detect_all_preferences(cls, content: str) -> Dict[str, str]:
        """Detect all preferences from file content."""
        return {
            "test_framework": cls.detect_test_framework(content),
            "code_style": cls.detect_code_style(content),
            "naming_convention": cls.detect_naming_convention(content),
            "import_style": cls.detect_import_style(content),
        }


class PreferenceManager:
    """
    Manages user preferences with automatic learning.

    Preferences are learned from:
    - Existing code in the project
    - User corrections and feedback
    - Repeated patterns in generated code

    Preferences are used to:
    - Generate code matching user style
    - Suggest appropriate tools and frameworks
    - Avoid style mismatches
    """

    # Preference categories and their weights
    CATEGORIES = {
        "test_framework": {"weight": 1.0, "default": "pytest"},
        "code_style": {"weight": 0.8, "default": "black"},
        "naming_convention": {"weight": 0.9, "default": "snake_case"},
        "import_style": {"weight": 0.7, "default": "absolute"},
        "docstring_style": {"weight": 0.6, "default": "google"},
        "error_handling": {"weight": 0.8, "default": "explicit"},
    }

    def __init__(self):
        self.state = get_state_store()
        self._cache: Dict[str, Any] = {}
        self._load_preferences()

    def _load_preferences(self):
        """Load preferences from database."""
        try:
            prefs = self.state.get("user_preferences")
            if prefs:
                self._cache = json.loads(prefs)
            else:
                self._cache = {}
        except Exception as e:
            warning(f"Failed to load preferences: {e}")
            self._cache = {}

    def _save_preferences(self):
        """Save preferences to database."""
        try:
            self.state.set("user_preferences", json.dumps(self._cache))
        except Exception as e:
            warning(f"Failed to save preferences: {e}")

    def learn_from_file(self, path: str, content: str) -> Dict[str, str]:
        """
        Learn preferences from a file.

        Args:
            path: File path (used to determine file type)
            content: File content to analyze

        Returns:
            Dictionary of detected preferences
        """
        if not path.endswith(".py"):
            return {}

        detected = PreferenceDetector.detect_all_preferences(content)

        # Update preferences with detected values
        for key, value in detected.items():
            if value:
                self._update_preference(key, value, confidence=0.3)

        return detected

    def learn_from_files(self, files: List[tuple]) -> Dict[str, List[str]]:
        """
        Learn preferences from multiple files.

        Args:
            files: List of (path, content) tuples

        Returns:
            Dictionary of preference -> list of detected values
        """
        all_detected = defaultdict(list)

        for path, content in files:
            detected = self.learn_from_file(path, content)
            for key, value in detected.items():
                if value:
                    all_detected[key].append(value)

        # Aggregate results
        for key, values in all_detected.items():
            if values:
                # Use most common value
                most_common = max(set(values), key=values.count)
                self._update_preference(key, most_common, confidence=0.5)

        return dict(all_detected)

    def _update_preference(self, key: str, value: str, confidence: float = 0.3):
        """
        Update a preference with new evidence.

        Args:
            key: Preference category
            value: Detected value
            confidence: Confidence level (0.0-1.0)
        """
        if key not in self._cache:
            self._cache[key] = {
                "value": value,
                "confidence": confidence,
                "observations": 1,
            }
        else:
            current = self._cache[key]
            # Exponential moving average
            alpha = confidence
            if current["value"] == value:
                # Same value - increase confidence
                current["confidence"] = min(1.0, current["confidence"] + alpha * 0.2)
                current["observations"] += 1
            else:
                # Different value - weighted average
                old_weight = 1.0 - alpha
                new_weight = alpha
                if current["confidence"] > 0.7:
                    # Strong existing preference, don't change easily
                    return
                current["value"] = value
                current["confidence"] = confidence
                current["observations"] += 1

        self._save_preferences()

    def learn_from_correction(self, category: str, value: str):
        """
        Learn from explicit user correction.

        Args:
            category: Preference category (e.g., "test_framework")
            value: Correct value (e.g., "pytest")
        """
        info(f"Learning preference: {category} = {value}")
        self._update_preference(category, value, confidence=1.0)

    def get(self, category: str, default: str = None) -> Optional[str]:
        """
        Get a preference value.

        Args:
            category: Preference category
            default: Default value if not learned

        Returns:
            Preferred value or default
        """
        if category in self._cache:
            entry = self._cache[category]
            if entry["confidence"] > 0.5:
                return entry["value"]
        return default or self.CATEGORIES.get(category, {}).get("default")

    def get_all(self) -> Dict[str, str]:
        """Get all preferences with sufficient confidence."""
        result = {}
        for category, config in self.CATEGORIES.items():
            value = self.get(category)
            if value:
                result[category] = value
        return result

    def get_confidence(self, category: str) -> float:
        """Get confidence level for a preference."""
        if category in self._cache:
            return self._cache[category].get("confidence", 0.0)
        return 0.0

    def clear(self):
        """Clear all learned preferences."""
        self._cache = {}
        self.state.delete("user_preferences")
        info("Preferences cleared")

    def status(self) -> Dict[str, Any]:
        """Get preference status."""
        return {
            "preferences": self.get_all(),
            "confidence": {
                cat: self.get_confidence(cat)
                for cat in self.CATEGORIES
            },
            "total_observations": sum(
                self._cache.get(cat, {}).get("observations", 0)
                for cat in self.CATEGORIES
            ),
        }


# Global singleton
_preferences: Optional[PreferenceManager] = None


def get_preferences() -> PreferenceManager:
    """Get the global preference manager."""
    global _preferences
    if _preferences is None:
        _preferences = PreferenceManager()
    return _preferences


def reset_preferences():
    """Reset the preference manager (for testing)."""
    global _preferences
    if _preferences:
        _preferences = None
