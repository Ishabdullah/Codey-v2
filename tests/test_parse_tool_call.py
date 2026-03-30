#!/usr/bin/env python3
"""
test_parse_tool_call — Tool call extraction from model output.

Verifies that parse_tool_call correctly extracts structured tool calls
from various model output formats (JSON in <tool> tags, rogue tags,
block-style write_file, malformed JSON, etc.).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from core.agent import parse_tool_call


class TestParseToolCall:
    """Standard <tool> JSON format."""

    def test_standard_json_tool_tag(self):
        raw = '<tool>\n{"name": "write_file", "args": {"path": "foo.py", "content": "x"}}\n</tool>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "write_file"
        assert result["args"]["path"] == "foo.py"

    def test_shell_tool_call(self):
        raw = '<tool>\n{"name": "shell", "args": {"command": "python test.py"}}\n</tool>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "shell"
        assert result["args"]["command"] == "python test.py"

    def test_read_file_tool_call(self):
        raw = '<tool>{"name": "read_file", "args": {"path": "main.py"}}</tool>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "read_file"

    def test_patch_file_tool_call(self):
        raw = '<tool>{"name": "patch_file", "args": {"path": "x.py", "old_str": "a", "new_str": "b"}}</tool>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "patch_file"

    def test_text_before_tool_tag(self):
        """Model output with prose before the tool tag should still parse."""
        raw = 'Let me create the file.\n<tool>\n{"name": "write_file", "args": {"path": "out.py", "content": "pass"}}\n</tool>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "write_file"

    def test_no_tool_tag_returns_none(self):
        raw = "I will create the file for you."
        result = parse_tool_call(raw)
        assert result is None

    def test_empty_string_returns_none(self):
        result = parse_tool_call("")
        assert result is None


class TestParseToolCallRogueTags:
    """Rogue <tool_name>{json}</tool_name> format some models emit."""

    def test_rogue_write_file_tag(self):
        raw = '<write_file>{"path": "app.py", "content": "print(1)"}</write_file>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "write_file"

    def test_rogue_shell_tag(self):
        raw = '<shell>{"command": "ls -la"}</shell>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "shell"


class TestParseToolCallBlockStyle:
    """Block-style <write_file path="...">...code...</write_file> format."""

    def test_block_style_write_file(self):
        raw = '<write_file path="hello.py">\nprint("hello world")\n</write_file>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "write_file"
        assert result["args"]["path"] == "hello.py"
        assert "hello world" in result["args"]["content"]

    def test_block_style_with_code_content(self):
        code = "def add(a, b):\n    return a + b\n"
        raw = f'<write_file path="math_utils.py">\n{code}</write_file>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["args"]["path"] == "math_utils.py"
        assert "def add" in result["args"]["content"]


class TestParseToolCallMalformed:
    """Malformed JSON that should still parse or gracefully fail."""

    def test_trailing_comma_in_tool(self):
        raw = '<tool>{"name": "shell", "args": {"command": "ls",}}</tool>'
        result = parse_tool_call(raw)
        assert result is not None
        assert result["name"] == "shell"

    def test_missing_closing_brace_in_standalone_json(self):
        """extract_json can repair missing closing brace when no trailing text."""
        from core.agent import extract_json
        raw = '{"name": "read_file", "args": {"path": "test.py"}'
        result = extract_json(raw)
        assert result is not None
        assert result["name"] == "read_file"

    def test_completely_invalid_json_returns_none(self):
        raw = "<tool>not json at all</tool>"
        result = parse_tool_call(raw)
        assert result is None

    def test_multiline_content_in_write_file(self):
        """write_file with multi-line content string."""
        raw = (
            '<tool>\n'
            '{"name": "write_file", "args": {"path": "a.py", "content": "line1\\nline2\\nline3"}}\n'
            '</tool>'
        )
        result = parse_tool_call(raw)
        assert result is not None
        assert result["args"]["content"] == "line1\nline2\nline3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
