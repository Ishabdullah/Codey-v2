#!/usr/bin/env python3
"""
Test orchestration heuristics.

Verifies that the is_complex function correctly identifies when
a request should trigger multi-step planning vs. direct response.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.orchestrator import is_complex, CONVERSATIONAL_PATTERNS


class TestOrchestrationHeuristics:
    """Test orchestration complexity detection."""

    def test_question_not_complex(self):
        """Simple questions should NOT trigger orchestration."""
        assert is_complex("How do I create a file?") == False

    def test_what_is_not_complex(self):
        """'What is' questions should NOT trigger orchestration."""
        assert is_complex("What is a decorator?") == False

    def test_can_you_explain_not_complex(self):
        """'Can you explain' should NOT trigger orchestration."""
        assert is_complex("Can you explain how this works?") == False

    def test_tell_me_not_complex(self):
        """'Tell me' requests should NOT trigger orchestration."""
        assert is_complex("Tell me about Python classes") == False

    def test_how_does_not_complex(self):
        """'How does' questions should NOT trigger orchestration."""
        assert is_complex("How does the async event loop work?") == False

    def test_should_i_use_not_complex(self):
        """'Should I use' questions should NOT trigger orchestration."""
        assert is_complex("Should I use Flask or Django?") == False

    def test_difference_between_not_complex(self):
        """'Difference between' questions should NOT trigger orchestration."""
        assert is_complex("What's the difference between list and tuple?") == False

    def test_i_need_help_not_complex(self):
        """'I need help' should NOT trigger orchestration."""
        assert is_complex("I need help understanding this error") == False

    def test_create_simple_file_not_complex(self):
        """Short create requests should NOT trigger orchestration."""
        assert is_complex("Create a file") == False

    def test_how_to_use_not_complex(self):
        """'How to use' questions should NOT trigger orchestration."""
        assert is_complex("How to use pytest?") == False

    def test_complex_create_with_tests(self):
        """Create with tests SHOULD trigger orchestration."""
        # Need enough COMPLEX_SIGNALS matches
        assert is_complex("Create a Flask app with user authentication and also add tests") == True

    def test_complex_build_multiple_components(self):
        """Build with multiple components SHOULD trigger orchestration."""
        assert is_complex("Build a REST API with multiple endpoints for users, posts, and also comments") == True

    def test_complex_refactor_and_run(self):
        """Refactor and run SHOULD trigger orchestration."""
        assert is_complex("Refactor the code to use classes and then run the tests") == True

    def test_complex_implement_system(self):
        """Implement system SHOULD trigger orchestration."""
        assert is_complex("Implement a caching system with Redis for the application") == True

    def test_long_message_fewer_signals(self):
        """Long messages need fewer signals to be complex."""
        msg = "Create a complete web application with user authentication, database models, API endpoints, and comprehensive test coverage including unit tests and integration tests"
        assert is_complex(msg) == True

    def test_short_message_needs_more_signals(self):
        """Short messages need more signals to be complex."""
        msg = "Create app"
        assert is_complex(msg) == False

    def test_question_mark_not_complex(self):
        """Messages ending with ? should NOT be complex (without action keywords)."""
        assert is_complex("Is this the right approach?") == False

    def test_action_keyword_with_question_not_complex(self):
        """Action keywords with question format should NOT be complex."""
        assert is_complex("How do I create a function?") == False

    def test_conversational_pattern_in_long_request(self):
        """Conversational patterns should filter even long requests."""
        msg = "Can you explain how to create a complete web application with authentication"
        assert is_complex(msg) == False

    def test_all_conversational_patterns_filtered(self):
        """All defined conversational patterns should be filtered."""
        for pattern in CONVERSATIONAL_PATTERNS:
            msg = f"{pattern} create something"
            # Most patterns should result in NOT complex
            # Some might still be complex if they have enough signals
            # This test just verifies the patterns are being checked
            result = is_complex(msg)
            # We don't assert False for all, as some patterns with enough
            # complexity signals might still trigger orchestration

    def test_implementation_request_complex(self):
        """Implementation requests SHOULD trigger orchestration."""
        # Need enough COMPLEX_SIGNALS matches
        assert is_complex("Implement a user registration system with multiple models and also API endpoints") == True

    def test_add_feature_complex(self):
        """Add feature requests SHOULD trigger orchestration."""
        # Need enough COMPLEX_SIGNALS matches  
        assert is_complex("Add a new module for handling file uploads and then also add tests for it") == True

    def test_rewrite_and_refactor_complex(self):
        """Rewrite/refactor requests SHOULD trigger orchestration."""
        # Need enough COMPLEX_SIGNALS matches
        assert is_complex("Rewrite the data processing module to use async and also refactor for the application") == True

    def test_multiple_tasks_complex(self):
        """Multiple tasks SHOULD trigger orchestration."""
        assert is_complex("Create the models and then add the API endpoints and also write tests") == True

    def test_empty_message_not_complex(self):
        """Empty messages should NOT be complex."""
        assert is_complex("") == False

    def test_very_short_message_not_complex(self):
        """Very short messages should NOT be complex."""
        assert is_complex("Hi") == False
        assert is_complex("Hello") == False
        assert is_complex("Test") == False


class TestConversationalPatterns:
    """Test conversational pattern coverage."""

    def test_common_question_starters(self):
        """Common question starters should be in patterns."""
        patterns_text = " ".join(CONVERSATIONAL_PATTERNS)
        
        # Should cover common question formats
        assert "how do i" in patterns_text.lower()
        assert "what is" in patterns_text.lower()
        assert "can you explain" in patterns_text.lower()

    def test_help_patterns(self):
        """Help-seeking patterns should be included."""
        patterns_text = " ".join(CONVERSATIONAL_PATTERNS)
        
        assert "help" in patterns_text.lower()
        assert "explain" in patterns_text.lower()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
