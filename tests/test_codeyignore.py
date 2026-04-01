import unittest
import os
from pathlib import Path
from core.context import load_file
from core.memory_v2 import memory as _mem

class TestCodeyIgnore(unittest.TestCase):
    def setUp(self):
        _mem.clear()
        self.env_file = Path(".env")
        self.env_file.write_text("SECRET=123")
        self.ignore_file = Path(".codeyignore")
        self.log_file = Path("test.log")
        self.secret_dir = Path("secrets")

    def tearDown(self):
        if self.env_file.exists(): os.remove(self.env_file)
        if self.ignore_file.exists(): os.remove(self.ignore_file)
        if self.log_file.exists(): os.remove(self.log_file)
        if self.secret_dir.exists():
            for f in self.secret_dir.iterdir():
                os.remove(f)
            os.rmdir(self.secret_dir)
        _mem.clear()

    def test_default_ignore(self):
        res = load_file(".env")
        self.assertIn("[ERROR] File is ignored", res)

    def test_custom_ignore(self):
        self.ignore_file.write_text("*.log\nsecrets/")
        self.log_file.write_text("some log")
        
        self.secret_dir.mkdir(exist_ok=True)
        secret_file = self.secret_dir / "pass.txt"
        secret_file.write_text("password")
        
        res_log = load_file("test.log")
        self.assertIn("[ERROR] File is ignored", res_log)
        
        res_pass = load_file("secrets/pass.txt")
        self.assertIn("[ERROR] File is ignored", res_pass)

if __name__ == "__main__":
    unittest.main()
