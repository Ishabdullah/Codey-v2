"""
MemoryManager — infinite context via tiered memory.

Budget allocation (32768 ctx, v2.6.6):
  System prompt:    ~500  (fixed)
  CODEY.md:         ~200  (fixed)
  Rolling summary:  ~400  (anchor)
  Relevant files:   ~1600 (dynamic, LRU + scored)
  Recent turns:     ~1000 (last 3 pairs)
  Current message:  ~400  (current)
  Response budget:  ~2048 (model output — aligned with max_tokens)
  Headroom:         ~26620 (large files, long sessions, big codebases)
"""
import os
import re
from pathlib import Path
from datetime import datetime
from utils.logger import info, warning
from utils.config import MODEL_CONFIG

# Token budget constants
CTX_TOTAL       = MODEL_CONFIG['n_ctx']
BUDGET_SYSTEM   = 500   # system prompt + CODEY.md (trimmed in v2.6.0)
BUDGET_SUMMARY  = 400   # rolling work summary
BUDGET_FILES    = 1600  # relevant file context (doubled for 8K)
BUDGET_TURNS    = 1000  # recent conversation turns
BUDGET_MESSAGE  = 400   # current user message
BUDGET_RESPONSE = MODEL_CONFIG['max_tokens']  # aligned with max_tokens (2048)

# Maximum file context budget for models with larger context windows (8k-32k)
MAX_FILE_CONTEXT_TOKENS = 4000

LRU_EVICT_AFTER = 3  # evict file after N turns without reference

from core.tokens import estimate_tokens

class FileRecord:
    """Tracks a loaded file with access metadata."""
    def __init__(self, path, content):
        self.path = path
        self.content = content
        self.tokens = estimate_tokens(content, path)
        self.last_used_turn = 0
        self.access_count = 1
        self.name = Path(path).name

    def relevance_score(self, message):
        """Score 0-1 based on keyword overlap with current message."""
        msg_words = set(re.findall(r'\w+', message.lower()))
        file_words = set(re.findall(r'\w+', self.content.lower()))
        name_words = set(re.findall(r'\w+', self.name.lower()))
        # Filename match is high signal
        name_overlap = len(msg_words & name_words) * 3
        content_overlap = len(msg_words & file_words)
        if not msg_words:
            return 0.5
        return min(1.0, (name_overlap + content_overlap) / (len(msg_words) + 1))

class MemoryManager:
    """
    Manages tiered context: files (LRU+scored), summary (compressed), turns (recent).
    """
    def __init__(self):
        self._files = {}        # path -> FileRecord
        self._summary = ''      # rolling compressed work log
        self._turn = 0          # current turn counter

    # ── File management ──────────────────────────────────────

    def load_file(self, path, content=None):
        """Add or refresh a file in memory."""
        p = Path(path).expanduser()
        if content is None:
            if not p.exists():
                p = Path(os.getcwd()) / path
            if not p.exists():
                return False
            try:
                content = p.read_text(encoding='utf-8', errors='replace')
            except Exception:
                return False
        key = str(p.resolve())
        if key in self._files:
            self._files[key].content = content
            self._files[key].tokens = estimate_tokens(content, str(p))
            self._files[key].last_used_turn = self._turn
            self._files[key].access_count += 1
        else:
            self._files[key] = FileRecord(key, content)
            self._files[key].last_used_turn = self._turn
        return True

    def unload_file(self, path):
        p = Path(path).expanduser().resolve()
        self._files.pop(str(p), None)

    def touch_file(self, path):
        """Mark file as recently used."""
        p = str(Path(path).expanduser().resolve())
        if p in self._files:
            self._files[p].last_used_turn = self._turn
            self._files[p].access_count += 1

    def evict_stale(self):
        """Remove files not accessed in LRU_EVICT_AFTER turns."""
        stale = [
            k for k, r in self._files.items()
            if self._turn - r.last_used_turn > LRU_EVICT_AFTER
        ]
        for k in stale:
            info(f'Evicting stale file: {Path(k).name}')
            del self._files[k]

    def list_files(self):
        return list(self._files.keys())

    # ── Summary / work log ───────────────────────────────────

    def append_to_summary(self, task, result):
        """Add a completed task to the rolling summary."""
        entry = f'[Turn {self._turn}] {task[:80]}: {result[:120]}'
        self._summary = (self._summary + '\n' + entry).strip()
        # Keep summary within token budget
        while estimate_tokens(self._summary) > BUDGET_SUMMARY:
            lines = self._summary.splitlines()
            if len(lines) <= 1:
                break
            # Drop oldest entries first
            self._summary = '\n'.join(lines[1:])

    def compress_summary(self, history):
        """Compress old history turns into summary using inference."""
        if len(history) < 8:
            return history
        from core.inference_v2 import infer
        old_turns = history[:-4]  # keep last 2 pairs fresh
        fresh_turns = history[-4:]
        text = '\n'.join(
            f"{m['role'].upper()}: {m['content'][:200]}"
            for m in old_turns
        )
        prompt = [
            {'role': 'system', 'content': 'Summarize this conversation in 3-5 bullet points. Be specific about files created, commands run, and errors fixed. Max 200 words.'},
            {'role': 'user',   'content': text}
        ]
        compressed = infer(prompt, stream=False)
        if compressed and not compressed.startswith('[ERROR]'):
            timestamp = datetime.now().strftime('%H:%M')
            self._summary = f'[Session work as of {timestamp}]\n' + compressed.strip()
            info('Compressed old turns into summary.')
        return fresh_turns

    def get_summary(self):
        return self._summary

    # ── Context assembly ─────────────────────────────────────

    def select_files_for_context(self, message, budget=BUDGET_FILES):
        """
        Score all loaded files by relevance to message,
        return as many as fit within budget (highest score first).
        
        Respects MAX_FILE_CONTEXT_TOKENS cap to prevent context overflow
        on models with 8k-32k context windows.
        """
        if not self._files:
            return []
        
        # Apply maximum budget cap to prevent context overflow
        effective_budget = min(budget, MAX_FILE_CONTEXT_TOKENS)
        
        scored = sorted(
            self._files.values(),
            key=lambda r: (r.relevance_score(message), r.last_used_turn),
            reverse=True
        )
        selected = []
        used = 0
        for record in scored:
            if used + record.tokens <= effective_budget:
                selected.append(record)
                used += record.tokens
            else:
                # Try to fit a truncated version
                remaining = effective_budget - used
                marker = '\n...[truncated]'

                # Use same heuristic as estimate_tokens
                code_exts = {".py", ".js", ".ts", ".c", ".cpp", ".h", ".rs", ".go"}
                is_code = any(record.path.endswith(ext) for ext in code_exts)
                multiplier = 3 if is_code else 4

                marker_tokens = len(marker) // multiplier
                if remaining > marker_tokens + 10:
                    # Calculate max allowed chars for the remaining tokens
                    # (chars // multiplier) <= remaining
                    # => chars <= remaining * multiplier + (multiplier - 1)
                    max_chars = (remaining * multiplier) + (multiplier - 1)
                    truncate_at = max_chars - len(marker)

                    truncated = record.content[:truncate_at]
                    tr = FileRecord(record.path, truncated + marker)
                    tr.last_used_turn = record.last_used_turn
                    # Re-verify tokens just in case
                    if used + tr.tokens <= effective_budget:
                        selected.append(tr)
                break
        return selected

    def build_file_block(self, message):
        """Build <file> XML block for selected files."""
        selected = self.select_files_for_context(message)
        if not selected:
            return ''
        blocks = []
        for r in selected:
            blocks.append(f'<file path="{r.name}">\n{r.content}\n</file>')
        return '\n'.join(blocks)

    def tick(self):
        """Advance turn counter and evict stale files."""
        self._turn += 1
        self.evict_stale()

    def clear(self):
        self._files.clear()
        self._summary = ''
        self._turn = 0

    def status(self):
        """Return dict of memory stats."""
        return {
            'files': len(self._files),
            'file_names': [Path(k).name for k in self._files],
            'summary_tokens': estimate_tokens(self._summary),
            'turn': self._turn,
        }


# Global singleton
memory = MemoryManager()
