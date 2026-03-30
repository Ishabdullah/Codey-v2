#!/usr/bin/env python3
"""
test_breadth — classify_breadth_need() unit tests.

Verifies that task complexity classification returns the correct
recursion-depth bucket: "minimal" (Q&A), "standard" (single-file),
or "deep" (multi-file / complex API tasks).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.recursive import classify_breadth_need


class TestMinimal:
    """Q&A and short conversational messages should classify as minimal."""

    def test_simple_question(self):
        assert classify_breadth_need("What is a decorator?") == "minimal"

    def test_how_question(self):
        assert classify_breadth_need("How does async/await work?") == "minimal"

    def test_question_mark(self):
        assert classify_breadth_need("Is Python pass-by-reference?") == "minimal"

    def test_explain_request(self):
        assert classify_breadth_need("Explain how closures work in Python") == "minimal"

    def test_hello(self):
        assert classify_breadth_need("Hello!") == "minimal"

    def test_thanks(self):
        assert classify_breadth_need("Thanks, that works!") == "minimal"

    def test_very_short_no_action(self):
        assert classify_breadth_need("list files") in ("minimal", "standard")


class TestStandard:
    """Single-file coding tasks should classify as standard."""

    def test_create_simple_file(self):
        result = classify_breadth_need("Create a Python script called hello.py that prints Hello World")
        assert result in ("standard", "deep")

    def test_write_function(self):
        result = classify_breadth_need("Write a function that calculates the factorial of a number")
        assert result in ("standard", "deep")

    def test_fix_bug(self):
        result = classify_breadth_need("Fix the bug in fibonacci.py where it crashes on negative input")
        assert result in ("standard", "deep")

    def test_edit_file(self):
        result = classify_breadth_need("Edit config.py and change the debug flag to False")
        assert result in ("standard", "deep")


class TestDeep:
    """Complex multi-step or multi-file tasks should classify as deep."""

    def test_full_api(self):
        result = classify_breadth_need(
            "Create a full REST API with authentication, database integration, "
            "and then write tests and deploy to the server"
        )
        assert result == "deep"

    def test_multi_file_with_tests(self):
        result = classify_breadth_need(
            "Build a Flask API for user management with SQLite database, "
            "add authentication, write integration tests, then migrate the schema"
        )
        assert result == "deep"

    def test_refactor_multiple_modules(self):
        result = classify_breadth_need(
            "Refactor the entire codebase to use async/await, update all tests, "
            "then deploy and run migration scripts"
        )
        assert result == "deep"

    def test_long_multi_step_prompt(self):
        # 50+ words with deep signals
        result = classify_breadth_need(
            "Create a budget tracking CLI tool called budget.py that tracks income "
            "and expenses with categories, shows a balance summary, saves everything "
            "to JSON with persistence between runs. Add authentication, write tests, "
            "run the tests, then initialize a git repo and commit everything."
        )
        assert result == "deep"


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_string(self):
        result = classify_breadth_need("")
        assert result in ("minimal", "standard", "deep")

    def test_action_word_only(self):
        result = classify_breadth_need("create")
        assert result in ("minimal", "standard")

    def test_action_in_question_context(self):
        # "How do I create a file?" has action but is QA
        result = classify_breadth_need("How do I create a file?")
        assert result == "minimal"

    def test_consistent_results(self):
        """Same input should always return same output (deterministic)."""
        msg = "Write a Python script to count words in a file"
        assert classify_breadth_need(msg) == classify_breadth_need(msg)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
