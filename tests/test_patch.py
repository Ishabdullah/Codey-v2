import unittest
import os
from pathlib import Path
from utils import config
config.AGENT_CONFIG["confirm_write"] = False
from tools.patch_tools import tool_patch_file
from core.filehistory import undo, _history

class TestPatch(unittest.TestCase):
    def setUp(self):
        self.test_file = Path("test_patch.txt")
        self.test_file.write_text("line 1\nline 2\nline 2\nline 3")
        _history.clear()

    def tearDown(self):
        if self.test_file.exists():
            os.remove(self.test_file)
        _history.clear()

    def test_unique_patch(self):
        res = tool_patch_file(str(self.test_file), "line 1", "LINE 1")
        self.assertIn("Patched", res)
        self.assertEqual(self.test_file.read_text(), "LINE 1\nline 2\nline 2\nline 3")

    def test_collision(self):
        res = tool_patch_file(str(self.test_file), "line 2", "LINE 2")
        self.assertIn("[ERROR] String found 2 times", res)

    def test_not_found(self):
        res = tool_patch_file(str(self.test_file), "missing", "whatever")
        self.assertIn("[ERROR] String not found", res)

    def test_undo_roundtrip(self):
        # Initial state
        initial_content = self.test_file.read_text()
        # Patch
        tool_patch_file(str(self.test_file), "line 1", "LINE 1")
        self.assertEqual(self.test_file.read_text(), "LINE 1\nline 2\nline 2\nline 3")
        # Undo
        undo(str(self.test_file))
        self.assertEqual(self.test_file.read_text(), initial_content)

if __name__ == "__main__":
    unittest.main()
