#!/usr/bin/env python3
"""
Test shell command structure validation.

Verifies that shell metacharacters are properly blocked to prevent injection attacks.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.shell_tools import validate_command_structure, SHELL_METACHARACTERS


class TestShellInjection:
    """Test shell command structure validation."""

    def test_blocks_semicolon_injection(self):
        """Semicolon should be blocked (command chaining)."""
        is_valid, error_msg = validate_command_structure("ls; rm -rf /")
        assert is_valid == False
        assert ";" in error_msg

    def test_blocks_double_ampersand(self):
        """&& should be blocked (conditional execution)."""
        is_valid, error_msg = validate_command_structure("ls && cat /etc/passwd")
        assert is_valid == False
        assert "&&" in error_msg

    def test_blocks_double_pipe(self):
        """|| should be blocked (alternative execution)."""
        is_valid, error_msg = validate_command_structure("ls || echo failed")
        assert is_valid == False
        assert "||" in error_msg

    def test_blocks_pipe(self):
        """| should be blocked (piping)."""
        is_valid, error_msg = validate_command_structure("ls | bash")
        assert is_valid == False
        assert "|" in error_msg

    def test_blocks_backticks(self):
        """Backticks should be blocked (command substitution)."""
        is_valid, error_msg = validate_command_structure("echo `whoami`")
        assert is_valid == False
        assert "`" in error_msg

    def test_blocks_dollar_paren(self):
        """$() should be blocked (command substitution)."""
        is_valid, error_msg = validate_command_structure("echo $(cat /etc/passwd)")
        assert is_valid == False
        assert "$(" in error_msg

    def test_blocks_dollar_brace(self):
        """${} should be blocked (variable expansion)."""
        is_valid, error_msg = validate_command_structure("echo ${PATH}")
        assert is_valid == False
        assert "${" in error_msg

    def test_blocks_process_substitution(self):
        """<() and >() should be blocked (process substitution)."""
        is_valid, error_msg = validate_command_structure("diff <(ls) <(cat)")
        assert is_valid == False
        assert "<(" in error_msg

    def test_allows_simple_ls(self):
        """Simple ls command should be allowed."""
        is_valid, error_msg = validate_command_structure("ls -la")
        assert is_valid == True
        assert error_msg == ""

    def test_allows_simple_cat(self):
        """Simple cat command should be allowed."""
        is_valid, error_msg = validate_command_structure("cat file.txt")
        assert is_valid == True
        assert error_msg == ""

    def test_allows_simple_grep(self):
        """Simple grep command should be allowed."""
        is_valid, error_msg = validate_command_structure("grep pattern file.py")
        assert is_valid == True
        assert error_msg == ""

    def test_allows_simple_find(self):
        """Simple find command should be allowed."""
        is_valid, error_msg = validate_command_structure("find . -name '*.py'")
        assert is_valid == True
        assert error_msg == ""

    def test_allows_python_script(self):
        """Python script execution should be allowed."""
        is_valid, error_msg = validate_command_structure("python3 script.py --arg value")
        assert is_valid == True
        assert error_msg == ""

    def test_allows_git_commands(self):
        """Git commands should be allowed."""
        is_valid, error_msg = validate_command_structure("git status")
        assert is_valid == True
        assert error_msg == ""

    def test_empty_command(self):
        """Empty command should be allowed (validation passes, execution may fail)."""
        is_valid, error_msg = validate_command_structure("")
        assert is_valid == True
        assert error_msg == ""

    def test_all_metacharacters_blocked(self):
        """Verify all defined metacharacters are actually blocked."""
        for char in SHELL_METACHARACTERS:
            cmd = f"ls {char} test"
            is_valid, error_msg = validate_command_structure(cmd)
            assert is_valid == False, f"Character '{char}' should be blocked"
            assert char in error_msg


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
