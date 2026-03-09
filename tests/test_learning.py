#!/usr/bin/env python3
"""
Tests for Codey-v2 learning systems.

Tests:
- User preference learning
- Error pattern database
- Strategy effectiveness tracking
- Integrated learning manager
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.preferences import PreferenceManager, PreferenceDetector, reset_preferences
from core.error_database import ErrorDatabase, ErrorPattern, reset_error_database
from core.strategy_tracker import StrategyTracker, reset_strategy_tracker
from core.learning import LearningManager, reset_learning_manager


class TestPreferenceDetector:
    """Test preference detection from code."""

    def test_detect_pytest(self):
        """Should detect pytest from test file."""
        content = """
import pytest

def test_login():
    assert True

@pytest.fixture
def client():
    pass
"""
        result = PreferenceDetector.detect_test_framework(content)
        assert result == "pytest"

    def test_detect_unittest(self):
        """Should detect unittest from test file."""
        content = """
import unittest

class TestLogin(unittest.TestCase):
    def test_login(self):
        self.assertEqual(1, 1)
"""
        result = PreferenceDetector.detect_test_framework(content)
        assert result == "unittest"

    def test_detect_snake_case(self):
        """Should detect snake_case naming."""
        content = """
def my_function():
    pass

def another_function():
    pass
"""
        result = PreferenceDetector.detect_naming_convention(content)
        assert result == "snake_case"

    def test_detect_all_preferences(self):
        """Should detect multiple preferences at once."""
        content = """
import pytest

def test_example():
    assert True
"""
        result = PreferenceDetector.detect_all_preferences(content)
        assert result["test_framework"] == "pytest"


class TestPreferenceManager:
    """Test preference learning and storage."""

    def setup_method(self):
        """Reset before each test."""
        reset_preferences()

    def test_learn_from_file(self):
        """Should learn preferences from a file."""
        pm = PreferenceManager()
        content = "import pytest\ndef test_x(): pass"
        result = pm.learn_from_file("test.py", content)
        assert result.get("test_framework") == "pytest"

    def test_learn_from_multiple_files(self):
        """Should aggregate preferences from multiple files."""
        pm = PreferenceManager()
        files = [
            ("test1.py", "import pytest\ndef test_a(): pass"),
            ("test2.py", "import pytest\ndef test_b(): pass"),
            ("test3.py", "import pytest\ndef test_c(): pass"),
        ]
        result = pm.learn_from_files(files)
        assert "pytest" in result.get("test_framework", [])

    def test_get_preference_with_confidence(self):
        """Should return preference only with sufficient confidence."""
        pm = PreferenceManager()
        # Learn multiple times to build confidence
        for _ in range(5):
            pm.learn_from_file("test.py", "import pytest\ndef test_x(): pass")
        
        result = pm.get("test_framework")
        assert result == "pytest"

    def test_learn_from_correction(self):
        """Should learn from explicit user correction."""
        pm = PreferenceManager()
        pm.learn_from_correction("test_framework", "pytest")
        result = pm.get("test_framework")
        assert result == "pytest"

    def test_status(self):
        """Should return status dict."""
        pm = PreferenceManager()
        status = pm.status()
        assert "preferences" in status
        assert "confidence" in status


class TestErrorDatabase:
    """Test error pattern database."""

    def setup_method(self):
        """Reset before each test."""
        reset_error_database()

    def test_record_error(self):
        """Should record error occurrence."""
        db = ErrorDatabase()
        key = db.record_error("ModuleNotFoundError", "No module named 'flask'")
        assert key is not None

    def test_record_fix(self):
        """Should record fix for error."""
        db = ErrorDatabase()
        key = db.record_error("ModuleNotFoundError", "No module named 'flask'")
        db.record_fix(key, "pip install flask", success=True)
        
        # Verify fix was recorded
        similar = db.find_similar_errors("ModuleNotFoundError", "No module named 'flask'")
        assert len(similar) > 0
        assert similar[0][0].success == True

    def test_learn_from_error_and_fix(self):
        """Should learn from complete error-fix cycle."""
        db = ErrorDatabase()
        db.learn_from_error(
            "ModuleNotFoundError",
            "No module named 'requests'",
            "pip install requests",
            success=True
        )
        
        stats = db.get_statistics()
        assert stats["total_fixed"] >= 1

    def test_find_similar_errors(self):
        """Should find similar error patterns."""
        db = ErrorDatabase()
        db.learn_from_error("ModuleNotFoundError", "No module named 'flask'", "pip install flask", True)
        db.learn_from_error("ModuleNotFoundError", "No module named 'requests'", "pip install requests", True)
        
        similar = db.find_similar_errors("ModuleNotFoundError", "No module named 'django'")
        assert len(similar) > 0

    def test_suggest_fix(self):
        """Should suggest fix for known error."""
        db = ErrorDatabase()
        db.learn_from_error("ModuleNotFoundError", "No module named 'flask'", "pip install flask", True)
        
        suggestion = db.suggest_fix("ModuleNotFoundError", "No module named 'flask'")
        assert suggestion == "pip install flask"

    def test_statistics(self):
        """Should return error statistics."""
        db = ErrorDatabase()
        db.learn_from_error("ValueError", "invalid literal", "fix input", True)
        db.learn_from_error("TypeError", "wrong type", "fix type", False)
        
        stats = db.get_statistics()
        assert "total_patterns" in stats
        assert "success_rate" in stats


class TestStrategyTracker:
    """Test strategy effectiveness tracking."""

    def setup_method(self):
        """Reset before each test."""
        reset_strategy_tracker()

    def test_record_attempt(self):
        """Should record strategy attempt."""
        tracker = StrategyTracker()
        tracker.record_attempt("use_patch", "write_failed", success=True, duration=1.5)
        
        stats = tracker.get_statistics()
        assert stats["total_attempts"] >= 1

    def test_get_best_strategy(self):
        """Should return best strategy for error type."""
        tracker = StrategyTracker()
        # Record multiple successful attempts
        for _ in range(5):
            tracker.record_attempt("use_patch", "write_failed", success=True, duration=1.0)
        for _ in range(3):
            tracker.record_attempt("retry", "write_failed", success=False, duration=2.0)
        
        best = tracker.get_best_strategy("write_failed")
        assert best == "use_patch"

    def test_get_strategies_for_error(self):
        """Should return ranked strategies."""
        tracker = StrategyTracker()
        tracker.record_attempt("install_dep", "ModuleNotFoundError", True, 5.0)
        tracker.record_attempt("fix_import", "ModuleNotFoundError", True, 2.0)
        
        strategies = tracker.get_strategies_for_error("ModuleNotFoundError")
        assert len(strategies) > 0
        # Higher success rate should be first
        assert strategies[0]["success_rate"] >= strategies[-1]["success_rate"]

    def test_statistics(self):
        """Should return strategy statistics."""
        tracker = StrategyTracker()
        tracker.record_attempt("test_strategy", "test_error", True, 1.0)
        
        stats = tracker.get_statistics()
        assert "total_strategies" in stats
        assert "overall_success_rate" in stats


class TestLearningManager:
    """Test integrated learning manager."""

    def setup_method(self):
        """Reset before each test."""
        reset_learning_manager()

    def test_learn_from_file(self):
        """Should learn preferences from file."""
        lm = LearningManager()
        result = lm.learn_from_file("test.py", "import pytest\ndef test_x(): pass")
        assert result.get("test_framework") == "pytest"

    def test_record_error_and_fix(self):
        """Should record error and fix."""
        lm = LearningManager()
        lm.learn_from_error_and_fix(
            "ModuleNotFoundError",
            "No module named 'flask'",
            "pip install flask",
            success=True,
            strategy="install_dependency"
        )
        
        status = lm.get_status()
        assert status["errors"]["total_fixed"] >= 1

    def test_get_best_strategy(self):
        """Should get best strategy from tracker."""
        lm = LearningManager()
        lm.record_strategy_attempt("use_patch", "write_failed", True, 1.0)
        lm.record_strategy_attempt("use_patch", "write_failed", True, 1.0)
        lm.record_strategy_attempt("use_patch", "write_failed", True, 1.0)
        
        best = lm.get_best_strategy("write_failed")
        assert best == "use_patch"

    def test_suggest_fix(self):
        """Should suggest fix from error database."""
        lm = LearningManager()
        lm.learn_from_error_and_fix(
            "ValueError",
            "invalid literal for int",
            "add try/except",
            success=True
        )
        
        suggestion = lm.suggest_fix("ValueError", "invalid literal for int")
        assert suggestion == "add try/except"

    def test_get_preference(self):
        """Should get learned preference."""
        lm = LearningManager()
        for _ in range(5):
            lm.learn_from_file("test.py", "import pytest\ndef test_x(): pass")
        
        pref = lm.get_preference("test_framework")
        assert pref == "pytest"

    def test_get_status(self):
        """Should return complete status."""
        lm = LearningManager()
        status = lm.get_status()
        
        assert "preferences" in status
        assert "errors" in status
        assert "strategies" in status


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
