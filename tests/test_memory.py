import unittest
from core.memory import MemoryManager, BUDGET_FILES, LRU_EVICT_AFTER

class TestMemory(unittest.TestCase):
    def setUp(self):
        self.memory = MemoryManager()

    def test_file_loading(self):
        self.memory.load_file("test.py", "print('hello')")
        self.assertEqual(len(self.memory.list_files()), 1)
        status = self.memory.status()
        self.assertIn("test.py", status["file_names"])

    def test_lru_eviction(self):
        # Load file at turn 0
        self.memory.load_file("file1.py", "content 1")
        # Turn 1
        self.memory.tick()
        # Turn 2
        self.memory.tick()
        # Turn 3
        self.memory.tick()
        # file1 should be evicted at turn 4 because 4 - 0 > 3
        self.memory.tick()
        self.assertEqual(len(self.memory.list_files()), 0)

    def test_lru_touch(self):
        self.memory.load_file("file1.py", "content 1")
        self.memory.tick()
        self.memory.tick()
        self.memory.touch_file("file1.py") # touch at turn 2
        self.memory.tick()
        self.memory.tick()
        self.memory.tick()
        self.memory.tick() # Turn 6. 6 - 2 = 4 > 3, so evicted
        self.assertEqual(len(self.memory.list_files()), 0)

    def test_budget_limits(self):
        # BUDGET_FILES is 800 tokens. Each char is ~0.25 tokens (len // 4).
        # So 800 tokens is about 3200 chars.
        large_content = "A" * 2000 # 500 tokens
        self.memory.load_file("large1.py", large_content)
        self.memory.load_file("large2.py", large_content)
        # Total tokens: 1000. This exceeds BUDGET_FILES (800).
        
        selected = self.memory.select_files_for_context("some prompt", budget=800)
        total_tokens = sum(r.tokens for r in selected)
        self.assertLessEqual(total_tokens, 800)
        self.assertEqual(len(selected), 2)
        # The second file should be truncated
        self.assertIn("...[truncated]", selected[1].content)

if __name__ == "__main__":
    unittest.main()
