import unittest
from core.agent import extract_json

class TestAgentParsing(unittest.TestCase):
    def test_standard_json(self):
        raw = '{"name": "test", "args": {"foo": "bar"}}'
        self.assertEqual(extract_json(raw), {"name": "test", "args": {"foo": "bar"}})

    def test_trailing_comma(self):
        raw = '{"name": "test", "args": {"foo": "bar"},}'
        self.assertEqual(extract_json(raw), {"name": "test", "args": {"foo": "bar"}})

    def test_extra_text(self):
        raw = '{"name": "test"} some extra text'
        self.assertEqual(extract_json(raw), {"name": "test"})

    def test_unescaped_newlines(self):
        raw = '{"name": "write_file", "args": {"path": "test.txt", "content": "line 1\nline 2"}}'
        result = extract_json(raw)
        self.assertEqual(result["args"]["content"], "line 1\nline 2")

    def test_brace_in_string(self):
        raw = '{"name": "test", "args": {"comment": "a brace } in a string"}}'
        result = extract_json(raw)
        self.assertEqual(result["args"]["comment"], "a brace } in a string")

    def test_incomplete_json(self):
        raw = '{"name": "test", "args": {"foo": "bar"'
        result = extract_json(raw)
        self.assertEqual(result, {"name": "test", "args": {"foo": "bar"}})

if __name__ == "__main__":
    unittest.main()
