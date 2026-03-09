#!/usr/bin/env python3
"""
Test hallucination detection.

Verifies that the is_hallucination function correctly identifies when
the model claims actions it didn't take.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent import is_hallucination


class TestHallucinationDetection:
    """Test hallucination detection logic."""

    def test_detects_past_tense_file_claim(self):
        """Past tense file creation claims without tool call should be detected."""
        response = "I have created the file test.py"
        user_message = "Create a file called test.py"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == True

    def test_detects_i_created_claim(self):
        """'I created' claims should be detected."""
        response = "I created the file for you"
        user_message = "Make a new file"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == True

    def test_detects_successfully_created(self):
        """'Successfully created' claims should be detected."""
        response = "The file has been successfully created"
        user_message = "Create a config file"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == True

    def test_allows_future_tense_intent(self):
        """Future tense statements should NOT be flagged as hallucination."""
        response = "I will create the file for you"
        user_message = "Create a file"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_allows_let_me_statement(self):
        """'Let me' statements should NOT be flagged as hallucination."""
        response = "Let me create that file for you"
        user_message = "Create a file"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_allows_ill_statement(self):
        """'I'll' statements should NOT be flagged as hallucination."""
        response = "I'll create the file right away"
        user_message = "Create a file"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_allows_can_statement(self):
        """'I can' statements should NOT be flagged as hallucination."""
        response = "I can help you create that file"
        user_message = "Create a file"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_not_hallucination_when_tool_called(self):
        """Claims should NOT be flagged if tool was actually called."""
        response = "I have created the file test.py"
        user_message = "Create a file"
        tools_used = ["write_file"]
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_detects_run_hallucination(self):
        """Past tense run claims without shell tool should be detected."""
        response = "I ran the tests successfully"
        user_message = "Run the tests"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_run == True

    def test_detects_executed_claim(self):
        """'Executed successfully' claims should be detected."""
        response = "The command executed successfully"
        user_message = "Execute the script"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_run == True

    def test_not_hallucination_for_unrelated_response(self):
        """Responses without action claims should not be flagged."""
        response = "Here's how you can create a file in Python..."
        user_message = "How do I create a file?"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False
        assert false_run == False

    def test_already_implemented_claim(self):
        """'Already implemented' claims should be detected."""
        response = "This capability is already implemented in the codebase"
        user_message = "Add a new feature"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == True

    def test_i_wrote_claim(self):
        """'I wrote' claims should be detected."""
        response = "I wrote the code to handle this"
        user_message = "Write code for this"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == True

    def test_i_modified_claim(self):
        """'I modified' claims should be detected when file action requested."""
        response = "I modified the function as requested"
        # Use "create" to trigger needs_file check
        user_message = "Create and modify this function"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        # "i modified" is in past_tense_claims list
        # This should be detected as potential hallucination
        assert false_file == True

    def test_next_i_will_not_flagged(self):
        """'Next I will' statements should NOT be flagged."""
        response = "Next I will run the tests to verify"
        user_message = "Fix the bug"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_im_going_to_not_flagged(self):
        """'I'm going to' statements should NOT be flagged."""
        response = "I'm going to create the file now"
        user_message = "Create a file"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_lets_create_not_flagged(self):
        """'Let's create' statements should NOT be flagged."""
        response = "Let's create a new module for this"
        user_message = "Create a module"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False

    def test_i_have_written_claim(self):
        """'I have written' claims should be detected."""
        response = "I have written the implementation"
        user_message = "Write an implementation"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == True

    def test_i_ran_the_claim(self):
        """'I ran the' claims should be detected for run hallucination."""
        response = "I ran the tests and they passed"
        user_message = "Run the tests"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_run == True

    def test_no_action_requested(self):
        """When no action is requested, claims should not be flagged."""
        response = "The file exists already"
        user_message = "What files are in the project?"
        tools_used = []
        
        false_file, false_run = is_hallucination(response, user_message, tools_used)
        assert false_file == False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
