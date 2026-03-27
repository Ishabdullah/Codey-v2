#!/usr/bin/env python3
"""
Hierarchical Memory for Codey-v2 (v2.7.0).

Four-tier memory system:
1. Working Memory   — currently edited files (LRU eviction by turn + token limit)
2. Project Memory   — key project files (CODEY.md, config) — never evicted
3. Long-term Memory — semantic search via embeddings (SQLite-backed, optional)
4. Episodic Memory  — append-only action log

The unified Memory class also exposes the full MemoryManager-compatible API
from core/memory.py (tick, load_file, unload_file, build_file_block,
compress_summary, get_summary, status, _files, etc.) so that core/memory.py
can be a thin shim that delegates here without any caller changes.

Migration note: This is the canonical memory system for v2.7.0+.
core/memory.py now imports from here.
"""

import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

from utils.logger import info, warning, error, success
from utils.config import CODEY_DIR, MODEL_CONFIG
from core.tokens import estimate_tokens

# ── Token budget constants ───────────────────────────────────────────────────
CTX_TOTAL               = MODEL_CONFIG['n_ctx']
# ── Budgets scaled for 32k context (were tuned for 8k) ───────────────────
BUDGET_SUMMARY          = 1200   # rolling work summary token cap
BUDGET_FILES            = 6000   # default file context budget
MAX_FILE_CONTEXT_TOKENS = 12000  # hard cap for large context windows
LRU_EVICT_AFTER         = 6      # evict file after N turns without reference


# ────────────────────────────────────────────────────────────────────────────
# Tier 1 — Working Memory
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class WorkingMemoryItem:
    """A file held in working memory with LRU and relevance metadata."""
    file_path: str
    content: str
    tokens: int
    loaded_at: int          # unix timestamp
    last_used_at: int       # unix timestamp (for wall-clock LRU)
    last_used_turn: int = 0  # agent turn counter (for turn-based LRU eviction)
    access_count: int = 1

    @property
    def name(self) -> str:
        """Filename without directory — used by /context display."""
        return Path(self.file_path).name

    def relevance_score(self, message: str) -> float:
        """Score 0-1 based on keyword overlap between message and file."""
        msg_words = set(re.findall(r'\w+', message.lower()))
        file_words = set(re.findall(r'\w+', self.content.lower()))
        name_words = set(re.findall(r'\w+', self.name.lower()))
        name_overlap = len(msg_words & name_words) * 3   # filename hit = high signal
        content_overlap = len(msg_words & file_words)
        if not msg_words:
            return 0.5
        return min(1.0, (name_overlap + content_overlap) / (len(msg_words) + 1))


class WorkingMemory:
    """
    Working memory for currently edited files.

    Two eviction strategies:
    - Token-based: evict LRU file when total tokens exceed max_tokens.
    - Turn-based:  evict files not accessed for LRU_EVICT_AFTER turns
                   (called by evict_stale() each tick).
    """

    def __init__(self, max_tokens: int = MAX_FILE_CONTEXT_TOKENS):
        self.max_tokens = max_tokens
        self._files: Dict[str, WorkingMemoryItem] = {}
        self._turn: int = 0

    def add(self, file_path: str, content: str, tokens: int):
        """Add or refresh a file in working memory."""
        now = int(time.time())
        if file_path in self._files:
            item = self._files[file_path]
            item.content = content
            item.tokens = tokens
            item.last_used_at = now
            item.last_used_turn = self._turn
            item.access_count += 1
        else:
            self._files[file_path] = WorkingMemoryItem(
                file_path=file_path,
                content=content,
                tokens=tokens,
                loaded_at=now,
                last_used_at=now,
                last_used_turn=self._turn,
            )
        self._evict_by_tokens()

    def get(self, file_path: str) -> Optional[str]:
        """Get file content and mark as recently used."""
        item = self._files.get(file_path)
        if item:
            item.last_used_at = int(time.time())
            item.last_used_turn = self._turn
            item.access_count += 1
            return item.content
        return None

    def touch(self, file_path: str):
        """Mark file as recently used without returning content."""
        item = self._files.get(file_path)
        if item:
            item.last_used_at = int(time.time())
            item.last_used_turn = self._turn
            item.access_count += 1

    def remove(self, file_path: str):
        """Remove a file from working memory."""
        if file_path in self._files:
            del self._files[file_path]

    def clear(self):
        """Clear all working memory (after task completes)."""
        count = len(self._files)
        self._files.clear()
        if count:
            info(f"Working memory: cleared {count} files")

    def evict_stale(self):
        """Remove files not accessed within LRU_EVICT_AFTER turns."""
        stale = [
            k for k, item in self._files.items()
            if self._turn - item.last_used_turn > LRU_EVICT_AFTER
        ]
        for k in stale:
            info(f"Working memory: evicted stale file {Path(k).name}")
            del self._files[k]

    def _evict_by_tokens(self):
        """Evict LRU files when over token limit.

        Files touched in the current turn are pinned — evicting a file the
        model is actively working with causes context loss and cascading errors.
        """
        total = sum(f.tokens for f in self._files.values())
        while total > self.max_tokens and self._files:
            # Only consider files NOT touched this turn
            candidates = {
                k: v for k, v in self._files.items()
                if v.last_used_turn < self._turn
            }
            if not candidates:
                break  # all files are current-turn — nothing safe to evict
            lru = min(candidates, key=lambda k: candidates[k].last_used_at)
            evicted = self._files.pop(lru)
            total -= evicted.tokens
            info(f"Working memory: token-evicted {evicted.name} ({evicted.tokens} tokens)")

    def select_for_context(self, message: str, budget: int = BUDGET_FILES) -> List[WorkingMemoryItem]:
        """
        Return files scored by relevance that fit within the token budget.
        Highest-scored files are included first; partially-truncated file
        appended if room remains.
        """
        if not self._files:
            return []
        effective = min(budget, MAX_FILE_CONTEXT_TOKENS)
        scored = sorted(
            self._files.values(),
            key=lambda item: (item.relevance_score(message), item.last_used_turn),
            reverse=True,
        )
        selected: List[WorkingMemoryItem] = []
        used = 0
        for item in scored:
            if used + item.tokens <= effective:
                selected.append(item)
                used += item.tokens
            else:
                remaining = effective - used
                marker = '\n...[truncated]'
                code_exts = {".py", ".js", ".ts", ".c", ".cpp", ".h", ".rs", ".go"}
                multiplier = 3 if any(item.file_path.endswith(e) for e in code_exts) else 4
                marker_tokens = len(marker) // multiplier
                if remaining > marker_tokens + 10:
                    max_chars = remaining * multiplier + (multiplier - 1)
                    truncated_content = item.content[: max_chars - len(marker)] + marker
                    trunc_tokens = estimate_tokens(truncated_content, item.file_path)
                    if used + trunc_tokens <= effective:
                        trunc_item = WorkingMemoryItem(
                            file_path=item.file_path,
                            content=truncated_content,
                            tokens=trunc_tokens,
                            loaded_at=item.loaded_at,
                            last_used_at=item.last_used_at,
                            last_used_turn=item.last_used_turn,
                        )
                        selected.append(trunc_item)
                break
        return selected

    def build_file_block(self, message: str) -> str:
        """Build the <file> XML block for the system prompt."""
        selected = self.select_for_context(message)
        if not selected:
            return ''
        blocks = [f'<file path="{item.name}">\n{item.content}\n</file>' for item in selected]
        return '\n'.join(blocks)

    def tick(self):
        """Advance turn counter."""
        self._turn += 1

    def get_all(self) -> Dict[str, str]:
        """Return all {path: content} pairs."""
        return {k: v.content for k, v in self._files.items()}

    def get_file_names(self) -> List[str]:
        """Return list of full paths currently loaded."""
        return list(self._files.keys())

    def status(self) -> dict:
        return {
            "files": len(self._files),
            "file_names": [item.name for item in self._files.values()],
            "total_tokens": sum(item.tokens for item in self._files.values()),
            "turn": self._turn,
        }


# ────────────────────────────────────────────────────────────────────────────
# Tier 2 — Project Memory
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class ProjectMemoryItem:
    """Item in project memory."""
    file_path: str
    content_hash: str
    loaded_at: int
    is_protected: bool


class ProjectMemory:
    """
    Project memory for key files (CODEY.md, config, README).
    Never evicted — loaded once at daemon start.
    """

    def __init__(self):
        self._files: Dict[str, ProjectMemoryItem] = {}
        self._protected_patterns = [
            "CODEY.md", "codey-v2.md", "README.md",
            "config.py", "config.json",
        ]

    def add(self, file_path: str, content: str, is_protected: bool = False):
        import hashlib
        content_hash = hashlib.md5(content.encode()).hexdigest()
        self._files[file_path] = ProjectMemoryItem(
            file_path=file_path,
            content_hash=content_hash,
            loaded_at=int(time.time()),
            is_protected=is_protected or self._is_protected(file_path),
        )

    def get(self, file_path: str) -> Optional[str]:
        """Returns the path if tracked, None otherwise (content not stored)."""
        return file_path if file_path in self._files else None

    def is_tracked(self, file_path: str) -> bool:
        return file_path in self._files

    def _is_protected(self, file_path: str) -> bool:
        return any(p in file_path for p in self._protected_patterns)

    def get_protected_files(self) -> List[str]:
        return [f.file_path for f in self._files.values() if f.is_protected]

    def status(self) -> dict:
        return {
            "files": len(self._files),
            "protected": len(self.get_protected_files()),
        }


# ────────────────────────────────────────────────────────────────────────────
# Tier 3 — Long-term Memory (optional — requires embedding server)
# ────────────────────────────────────────────────────────────────────────────

class LongTermMemory:
    """
    Long-term memory with semantic search.

    Stores file chunks as embeddings in SQLite.
    Requires the nomic-embed server (port 8082). Degrades gracefully
    if the embedding infrastructure is unavailable.
    """

    def __init__(self):
        self._store = None
        self._model = None
        self._available = False
        self._init_error: Optional[str] = None
        self._try_init()

    def _try_init(self):
        """Lazy-initialize the embedding backend. Silently skip if unavailable."""
        try:
            from core.embeddings import get_embedding_model, get_embedding_store
            self._store = get_embedding_store()
            self._model = get_embedding_model()
            self._available = True
        except Exception as e:
            self._init_error = str(e)
            # Long-term memory is optional — don't crash the agent if unavailable

    def store_file(self, file_path: str, content: str) -> int:
        if not self._available:
            return 0
        try:
            from core.embeddings import chunk_text
            chunks = chunk_text(content)
            embeddings_data = []
            for chunk_text_item, start, end in chunks:
                embedding = self._model.embed(chunk_text_item)
                if embedding:
                    embeddings_data.append((file_path, start, end, embedding))
            if embeddings_data:
                count = self._store.store_batch(embeddings_data)
                return count
        except Exception as e:
            warning(f"Long-term memory store_file failed: {e}")
        return 0

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        if not self._available:
            return []
        try:
            query_embedding = self._model.embed(query)
            if not query_embedding:
                return []
            return self._store.search(query_embedding, limit)
        except Exception:
            return []

    def remove_file(self, file_path: str) -> int:
        if not self._available:
            return 0
        try:
            return self._store.delete_by_file(file_path)
        except Exception:
            return 0

    def count(self) -> int:
        if not self._available:
            return 0
        try:
            return self._store.count()
        except Exception:
            return 0

    def status(self) -> dict:
        return {
            "available": self._available,
            "embeddings": self.count(),
            "init_error": self._init_error,
        }


# ────────────────────────────────────────────────────────────────────────────
# Tier 4 — Episodic Memory
# ────────────────────────────────────────────────────────────────────────────

class EpisodicMemory:
    """
    Episodic memory — append-only log of actions.
    Stored in SQLite via the state store.
    Degrades gracefully if the state store lacks action-log methods.
    """

    def __init__(self):
        try:
            from core.state import get_state_store
            self._state = get_state_store()
        except Exception:
            self._state = None

    def log(self, action: str, details: str = None):
        if self._state and hasattr(self._state, 'log_action'):
            try:
                self._state.log_action(action, details)
            except Exception:
                pass

    def get_recent(self, limit: int = 50) -> List[Dict]:
        if self._state and hasattr(self._state, 'get_recent_actions'):
            try:
                return self._state.get_recent_actions(limit)
            except Exception:
                pass
        return []

    def get_since(self, timestamp: int) -> List[Dict]:
        if self._state and hasattr(self._state, 'get_actions_since'):
            try:
                return self._state.get_actions_since(timestamp)
            except Exception:
                pass
        return []

    def status(self) -> dict:
        return {"recent_actions": len(self.get_recent(10))}


# ────────────────────────────────────────────────────────────────────────────
# Unified Memory — combines all four tiers + MemoryManager-compatible API
# ────────────────────────────────────────────────────────────────────────────

class Memory:
    """
    Unified hierarchical memory system.

    Combines all four tiers AND exposes the full MemoryManager-compatible
    API so core/memory.py can be a transparent shim:

        load_file, unload_file, touch_file, list_files,
        build_file_block, select_files_for_context,
        append_to_summary, compress_summary, get_summary,
        tick, clear, evict_stale, status, _files (property)
    """

    def __init__(self):
        self.working  = WorkingMemory()
        self.project  = ProjectMemory()
        self.longterm = LongTermMemory()
        self.episodic = EpisodicMemory()
        self._turn    = 0
        self._summary = ''   # rolling compressed work log

    # ── MemoryManager-compatible file API ────────────────────────────────────

    def load_file(self, path: str, content: str = None) -> bool:
        """
        Load a file into working memory.
        Reads from disk if content is not provided.
        Also stores in long-term memory (embeddings) if available.
        """
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
        tokens = estimate_tokens(content, key)
        self.working.add(key, content, tokens)
        # Long-term indexing deferred — store_file chunks the content and
        # calls the embedding server, which is too heavy during a file write
        # (causes OOM on memory-constrained devices).  Long-term indexing
        # happens lazily on read_file or via /index command instead.
        return True

    def unload_file(self, path: str):
        """Remove a file from working memory."""
        key = str(Path(path).expanduser().resolve())
        self.working.remove(key)

    def touch_file(self, path: str):
        """Mark a file as recently used (prevents LRU eviction)."""
        key = str(Path(path).expanduser().resolve())
        self.working.touch(key)

    def list_files(self) -> List[str]:
        """Return list of fully-resolved paths currently in working memory."""
        return self.working.get_file_names()

    def build_file_block(self, message: str = '') -> str:
        """Build the <file> XML block for the system prompt."""
        return self.working.build_file_block(message)

    def select_files_for_context(self, message: str, budget: int = BUDGET_FILES) -> list:
        """Return relevance-scored WorkingMemoryItem list that fits budget."""
        return self.working.select_for_context(message, budget)

    def evict_stale(self):
        """Evict files not accessed in the last LRU_EVICT_AFTER turns."""
        self.working.evict_stale()

    # ── Summary / work log ───────────────────────────────────────────────────

    def append_to_summary(self, task: str, result: str):
        """Add a completed task entry to the rolling summary."""
        entry = f'[Turn {self._turn}] {task[:80]}: {result[:120]}'
        self._summary = (self._summary + '\n' + entry).strip()
        # Trim oldest entries to stay within budget
        while estimate_tokens(self._summary) > BUDGET_SUMMARY:
            lines = self._summary.splitlines()
            if len(lines) <= 1:
                break
            self._summary = '\n'.join(lines[1:])

    def compress_summary(self, history: list) -> list:
        """
        Compress old history turns into the rolling summary via inference.
        Returns the trimmed history (last 4 messages kept fresh).
        """
        if len(history) < 8:
            return history
        try:
            from core.inference_v2 import infer
            old_turns  = history[:-4]
            fresh_turns = history[-4:]
            text = '\n'.join(
                f"{m['role'].upper()}: {m['content'][:200]}"
                for m in old_turns
            )
            prompt = [
                {
                    'role': 'system',
                    'content': (
                        'Summarize this conversation in 3-5 bullet points. '
                        'Be specific about files created, commands run, and errors fixed. '
                        'Max 200 words.'
                    ),
                },
                {'role': 'user', 'content': text},
            ]
            compressed = infer(prompt, stream=False)
            if compressed and not compressed.startswith('[ERROR]'):
                ts = datetime.now().strftime('%H:%M')
                self._summary = f'[Session work as of {ts}]\n' + compressed.strip()
                info('Compressed old turns into summary.')
            return fresh_turns
        except Exception as e:
            warning(f"compress_summary failed: {e}")
            return history

    def get_summary(self) -> str:
        """Return the current rolling summary string."""
        return self._summary

    # ── Turn management ──────────────────────────────────────────────────────

    def tick(self):
        """
        Advance the turn counter, run LRU eviction, and tick working memory.
        Call once at the start of each agent turn.
        """
        self._turn += 1
        self.working.tick()
        self.working.evict_stale()
        self.episodic.log("tick", f"Turn {self._turn}")

    def clear(self):
        """Clear all working memory and reset the rolling summary."""
        self.working.clear()
        self._summary = ''

    # ── Higher-level helpers (v2 additions) ──────────────────────────────────

    def add_to_working(self, file_path: str, content: str, tokens: int):
        """Directly add pre-tokenised content to working memory."""
        key = str(Path(file_path).expanduser().resolve())
        self.working.add(key, content, tokens)

    def add_to_project(self, file_path: str, content: str, is_protected: bool = False):
        """Add a file to project memory (never evicted)."""
        self.project.add(file_path, content, is_protected)

    def store_in_longterm(self, file_path: str, content: str):
        """Index a file in long-term (embedding) memory."""
        self.longterm.store_file(file_path, content)

    def log_action(self, action: str, details: str = None):
        """Append an entry to episodic memory."""
        self.episodic.log(action, details)

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Semantic search over long-term memory."""
        return self.longterm.search(query, limit)

    def get_working_content(self) -> Dict[str, str]:
        """Return all {path: content} pairs from working memory."""
        return self.working.get_all()

    def clear_working(self):
        """Clear working memory only (keeps summary and project memory)."""
        self.working.clear()

    # ── MemoryManager-compatible _files property ─────────────────────────────

    @property
    def _files(self) -> Dict[str, 'WorkingMemoryItem']:
        """
        Direct access to the working memory files dict.
        Exposed for backward compatibility with main.py /context command,
        which iterates this dict to display token counts and LRU ages.
        """
        return self.working._files

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """
        Return a flat status dict compatible with the MemoryManager API.

        Keys consumed by callers:
          files, file_names, summary_tokens, turn   (main.py /context, /memory-status)
          working, project, longterm, episodic       (four-tier detail)
        """
        wstatus = self.working.status()
        return {
            # ── MemoryManager-compatible flat keys ──────────────────────────
            'files':         wstatus['files'],
            'file_names':    wstatus['file_names'],
            'summary_tokens': estimate_tokens(self._summary),
            'turn':          self._turn,
            # ── v2 hierarchical detail ───────────────────────────────────────
            'working':   wstatus,
            'project':   self.project.status(),
            'longterm':  self.longterm.status(),
            'episodic':  self.episodic.status(),
        }


# ────────────────────────────────────────────────────────────────────────────
# Global singleton
# ────────────────────────────────────────────────────────────────────────────

_memory: Optional[Memory] = None


def get_memory() -> Memory:
    """Get (or create) the global Memory singleton."""
    global _memory
    if _memory is None:
        _memory = Memory()
    return _memory


def reset_memory():
    """Reset the global singleton (used in tests)."""
    global _memory
    _memory = None
