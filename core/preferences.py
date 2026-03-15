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

    # Type hint usage
    TYPE_HINT_PATTERNS = {
        "yes": [
            r"def \w+\(.*:.*\)\s*->",   # return type annotation
            r"def \w+\(.*:\s*\w+",       # parameter annotation
            r":\s*(?:str|int|float|bool|list|dict|tuple|set|Optional|List|Dict|Union)\b",
        ],
        "no": [
            r"def \w+\([^:)]+\):",       # args with no annotations
        ],
    }

    # Async style
    ASYNC_PATTERNS = {
        "async": [
            r"async def ",
            r"await ",
            r"asyncio\.",
            r"aiohttp",
            r"async with ",
            r"async for ",
        ],
        "sync": [],  # default assumption
    }

    # Preferred HTTP/web libraries
    HTTP_LIBS = {
        "httpx":    [r"import httpx", r"from httpx import"],
        "requests": [r"import requests", r"from requests import"],
        "aiohttp":  [r"import aiohttp", r"from aiohttp import"],
        "urllib":   [r"import urllib", r"from urllib"],
    }

    # Preferred CLI libraries
    CLI_LIBS = {
        "click":    [r"import click", r"from click import", r"@click\."],
        "argparse": [r"import argparse", r"ArgumentParser\("],
        "typer":    [r"import typer", r"from typer import"],
    }

    # Logging style
    LOG_STYLES = {
        "logging": [r"import logging", r"logging\.get[Ll]ogger", r"logger\.(?:info|debug|warning|error)"],
        "print":   [r"\bprint\("],
        "loguru":  [r"from loguru import", r"import loguru"],
        "rich":    [r"from rich import", r"console\.print\("],
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
    def detect_type_hints(cls, content: str) -> Optional[str]:
        """Detect whether type hints are used."""
        yes_score = sum(
            1 for p in cls.TYPE_HINT_PATTERNS["yes"]
            if re.search(p, content, re.MULTILINE)
        )
        no_score = len(re.findall(cls.TYPE_HINT_PATTERNS["no"][0], content, re.MULTILINE))
        if yes_score >= 2:
            return "yes"
        if no_score > yes_score * 2:
            return "no"
        return None

    @classmethod
    def detect_async_style(cls, content: str) -> Optional[str]:
        """Detect whether async/await patterns are used."""
        score = sum(
            1 for p in cls.ASYNC_PATTERNS["async"]
            if re.search(p, content, re.MULTILINE)
        )
        return "async" if score >= 2 else None

    @classmethod
    def detect_preferred_library(cls, content: str, lib_map: Dict, category: str) -> Optional[str]:
        """Generic detector for preferred library from a map."""
        scores = defaultdict(int)
        for lib, patterns in lib_map.items():
            for p in patterns:
                if re.search(p, content, re.MULTILINE):
                    scores[lib] += 1
        return max(scores, key=scores.get) if scores else None

    @classmethod
    def detect_log_style(cls, content: str) -> Optional[str]:
        """Detect preferred logging style."""
        scores = defaultdict(int)
        for style, patterns in cls.LOG_STYLES.items():
            for p in patterns:
                scores[style] += len(re.findall(p, content, re.MULTILINE))
        if not any(scores.values()):
            return None
        return max(scores, key=scores.get)

    @classmethod
    def detect_all_preferences(cls, content: str) -> Dict[str, str]:
        """Detect all preferences from file content."""
        return {
            "test_framework":    cls.detect_test_framework(content),
            "code_style":        cls.detect_code_style(content),
            "naming_convention": cls.detect_naming_convention(content),
            "import_style":      cls.detect_import_style(content),
            "type_hints":        cls.detect_type_hints(content),
            "async_style":       cls.detect_async_style(content),
            "http_library":      cls.detect_preferred_library(content, cls.HTTP_LIBS, "http_library"),
            "cli_library":       cls.detect_preferred_library(content, cls.CLI_LIBS, "cli_library"),
            "log_style":         cls.detect_log_style(content),
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
        "test_framework":    {"weight": 1.0, "default": "pytest"},
        "code_style":        {"weight": 0.8, "default": "black"},
        "naming_convention": {"weight": 0.9, "default": "snake_case"},
        "import_style":      {"weight": 0.7, "default": "absolute"},
        "docstring_style":   {"weight": 0.6, "default": "google"},
        "error_handling":    {"weight": 0.8, "default": "explicit"},
        "type_hints":        {"weight": 0.8, "default": None},
        "async_style":       {"weight": 0.7, "default": None},
        "http_library":      {"weight": 0.9, "default": None},
        "cli_library":       {"weight": 0.9, "default": None},
        "log_style":         {"weight": 0.7, "default": None},
    }

    # Natural language patterns for extracting preferences from user messages.
    # Each entry: (regex, category, value_group_or_literal)
    # value_group_or_literal: int → capture group index; str → literal value
    NL_PATTERNS = [
        # "always use X" / "use X" / "prefer X" / "I like X"
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(pytest|unittest)", "test_framework", 1),
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(black|pep8|ruff)", "code_style", 1),
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(httpx|requests|aiohttp|urllib)", "http_library", 1),
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(click|argparse|typer)", "cli_library", 1),
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(loguru|logging|rich)\s*(?:for\s*log(?:ging)?)?", "log_style", 1),
        # type hints
        (r"(?:always (?:add|use|include)|i (?:want|prefer|like))\s+type\s*hints?", "type_hints", "yes"),
        (r"(?:don'?t|no|skip|avoid)\s+type\s*hints?", "type_hints", "no"),
        # async
        (r"(?:always use|prefer|use|i (?:prefer|like|want))\s+async", "async_style", "async"),
        # docstrings
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(google|numpy|sphinx|epytext)\s+docstrings?", "docstring_style", 1),
        # error handling
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(explicit|try.except|raise)\s*(?:error\s*handling)?", "error_handling", 1),
        # naming
        (r"(?:always use|prefer|use|i (?:prefer|like|want)|stick to)\s+(snake_case|camelCase|PascalCase)\s*(?:naming)?", "naming_convention", 1),
        # "don't use X" → negative preference
        (r"(?:don'?t|do not|never|avoid)\s+use\s+(requests)\b", "http_library", "httpx"),
        (r"(?:don'?t|do not|never|avoid)\s+use\s+(argparse)\b", "cli_library", "click"),
        (r"(?:don'?t|do not|never|avoid)\s+use\s+print\b", "log_style", "logging"),
    ]

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

    def learn_from_message(self, message: str) -> Dict[str, str]:
        """
        Learn preferences from a natural language user message.

        Detects phrases like "always use pytest", "I prefer httpx",
        "don't use print", "add type hints", etc.

        Args:
            message: User's message text

        Returns:
            Dict of category -> value for any preferences detected
        """
        found = {}
        msg_lower = message.lower()
        for pattern, category, value_spec in PreferenceManager.NL_PATTERNS:
            m = re.search(pattern, msg_lower)
            if m:
                value = m.group(value_spec) if isinstance(value_spec, int) else value_spec
                if value:
                    self._update_preference(category, value, confidence=1.0)
                    found[category] = value
                    info(f"Learned preference from message: {category} = {value}")
        return found

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
        # Mirror high-confidence preferences to CODEY.md Conventions section
        if self._cache.get(key, {}).get("confidence", 0) >= 0.8:
            self._sync_to_codeymd(key, value)

    def _sync_to_codeymd(self, key: str, value: str):
        """Write a learned preference into the Conventions section of CODEY.md."""
        try:
            from core.codeymd import find_codeymd
            import os
            codeymd_path = find_codeymd()
            if not codeymd_path:
                return
            text = codeymd_path.read_text(encoding="utf-8", errors="replace")
            label_map = {
                "test_framework":    "Test framework",
                "code_style":        "Code style",
                "naming_convention": "Naming",
                "import_style":      "Imports",
                "docstring_style":   "Docstrings",
                "error_handling":    "Error handling",
                "type_hints":        "Type hints",
                "async_style":       "Async",
                "http_library":      "HTTP library",
                "cli_library":       "CLI library",
                "log_style":         "Logging",
            }
            label = label_map.get(key, key)
            entry = f"- {label}: {value}"
            # If a Conventions section exists, update or append the entry
            if "# Conventions" in text:
                lines = text.splitlines()
                new_lines = []
                in_conv = False
                entry_written = False
                for line in lines:
                    if line.strip() == "# Conventions":
                        in_conv = True
                        new_lines.append(line)
                        continue
                    if in_conv and line.startswith("# ") and line.strip() != "# Conventions":
                        # Next section — write entry before leaving if not done
                        if not entry_written:
                            new_lines.append(entry)
                            entry_written = True
                        in_conv = False
                    if in_conv and line.startswith(f"- {label}:"):
                        new_lines.append(entry)
                        entry_written = True
                        continue
                    new_lines.append(line)
                if in_conv and not entry_written:
                    new_lines.append(entry)
                codeymd_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            else:
                # No Conventions section — append one
                codeymd_path.write_text(
                    text.rstrip() + f"\n\n# Conventions\n{entry}\n",
                    encoding="utf-8"
                )
        except Exception:
            pass

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
