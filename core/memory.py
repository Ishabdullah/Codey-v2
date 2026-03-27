"""
core/memory.py — shim (v2.7.0).

The canonical memory implementation has moved to core/memory_v2.py.
This module re-exports the Memory class as MemoryManager and creates
the module-level `memory` singleton so all existing callers
(core/context.py, core/agent.py, main.py, prompts/layered_prompt.py)
continue to work without any changes.

Budget allocation reference (32768 ctx):
  System prompt:    ~500  (fixed)
  CODEY.md:         ~200  (fixed)
  Rolling summary:  ~400  (anchor — see BUDGET_SUMMARY in memory_v2)
  Relevant files:   ~1600 (dynamic, LRU + relevance scored)
  Recent turns:     ~1000 (last 3 pairs)
  Current message:  ~400  (current)
  Response budget:  ~2048 (model output)
  Headroom:         ~26620
"""

from core.memory_v2 import (
    Memory as MemoryManager,
    WorkingMemoryItem as FileRecord,
    get_memory,
    reset_memory,
    LRU_EVICT_AFTER,
    BUDGET_FILES,
    BUDGET_SUMMARY,
    MAX_FILE_CONTEXT_TOKENS,
    CTX_TOTAL,
)
from utils.config import MODEL_CONFIG

BUDGET_RESPONSE = MODEL_CONFIG['max_tokens']

# Global singleton — same object used by every caller that does
#   from core.memory import memory as _mem
memory = get_memory()
