#!/usr/bin/env python3
"""
Hierarchical Memory for Codey v2.

Four-tier memory system:
1. Working Memory - Currently edited files (evicted after task)
2. Project Memory - Key files like CODEY.md (never evicted)
3. Long-term Memory - Embeddings for semantic search
4. Episodic Memory - Log of actions taken
"""

import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from utils.logger import info, warning, error, success
from utils.config import CODEY_DIR
from core.embeddings import (
    get_embedding_model, get_embedding_store, 
    chunk_text, EmbeddingStore
)
from core.state import get_state_store


@dataclass
class WorkingMemoryItem:
    """Item in working memory."""
    file_path: str
    content: str
    tokens: int
    loaded_at: int
    last_used_at: int


@dataclass
class ProjectMemoryItem:
    """Item in project memory."""
    file_path: str
    content_hash: str
    loaded_at: int
    is_protected: bool


class WorkingMemory:
    """
    Working memory for currently edited files.
    
    Evicted after task completes.
    Fast in-memory access.
    """
    
    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self._files: Dict[str, WorkingMemoryItem] = {}
        self._turn: int = 0
    
    def add(self, file_path: str, content: str, tokens: int):
        """Add file to working memory."""
        now = int(time.time())
        self._files[file_path] = WorkingMemoryItem(
            file_path=file_path,
            content=content,
            tokens=tokens,
            loaded_at=now,
            last_used_at=now
        )
        info(f"Working memory: added {file_path} ({tokens} tokens)")
        
        # Evict if over limit
        self._evict_if_needed()
    
    def get(self, file_path: str) -> Optional[str]:
        """Get file content from working memory."""
        item = self._files.get(file_path)
        if item:
            item.last_used_at = int(time.time())
            return item.content
        return None
    
    def remove(self, file_path: str):
        """Remove file from working memory."""
        if file_path in self._files:
            del self._files[file_path]
            info(f"Working memory: removed {file_path}")
    
    def clear(self):
        """Clear all working memory (after task completes)."""
        count = len(self._files)
        self._files.clear()
        info(f"Working memory: cleared {count} files")
    
    def _evict_if_needed(self):
        """Evict oldest files if over token limit."""
        total_tokens = sum(f.tokens for f in self._files.values())
        
        while total_tokens > self.max_tokens and self._files:
            # Find least recently used
            lru_file = min(self._files.keys(), 
                          key=lambda f: self._files[f].last_used_at)
            evicted = self._files.pop(lru_file)
            total_tokens -= evicted.tokens
            info(f"Working memory: evicted {lru_file} ({evicted.tokens} tokens)")
    
    def get_all(self) -> Dict[str, str]:
        """Get all file contents."""
        return {f.file_path: f.content for f in self._files.values()}
    
    def get_file_names(self) -> List[str]:
        """Get list of file names in memory."""
        return list(self._files.keys())
    
    def status(self) -> dict:
        """Get working memory status."""
        return {
            "files": len(self._files),
            "file_names": self.get_file_names(),
            "total_tokens": sum(f.tokens for f in self._files.values()),
            "turn": self._turn,
        }
    
    def tick(self):
        """Increment turn counter."""
        self._turn += 1


class ProjectMemory:
    """
    Project memory for key files.
    
    Never evicted. Loaded at daemon start.
    Includes CODEY.md, config files, etc.
    """
    
    def __init__(self):
        self._files: Dict[str, ProjectMemoryItem] = {}
        self._protected_patterns = [
            "CODEY.md", "codey-v2.md", "README.md",
            "config.py", "config.json",
        ]
    
    def add(self, file_path: str, content: str, is_protected: bool = False):
        """Add file to project memory."""
        import hashlib
        content_hash = hashlib.md5(content.encode()).hexdigest()
        
        self._files[file_path] = ProjectMemoryItem(
            file_path=file_path,
            content_hash=content_hash,
            loaded_at=int(time.time()),
            is_protected=is_protected or self._is_protected(file_path)
        )
        info(f"Project memory: added {file_path}")
    
    def get(self, file_path: str) -> Optional[str]:
        """Get file content (returns None, content not stored)."""
        if file_path in self._files:
            return file_path  # Just confirm it's tracked
        return None
    
    def is_tracked(self, file_path: str) -> bool:
        """Check if file is in project memory."""
        return file_path in self._files
    
    def _is_protected(self, file_path: str) -> bool:
        """Check if file matches protected patterns."""
        return any(p in file_path for p in self._protected_patterns)
    
    def get_protected_files(self) -> List[str]:
        """Get list of protected files."""
        return [f.file_path for f in self._files.values() if f.is_protected]
    
    def status(self) -> dict:
        """Get project memory status."""
        return {
            "files": len(self._files),
            "protected": len(self.get_protected_files()),
        }


class LongTermMemory:
    """
    Long-term memory with semantic search.
    
    Uses embeddings for similarity search.
    Persists in SQLite.
    """
    
    def __init__(self):
        self.store = get_embedding_store()
        self.model = get_embedding_model()
    
    def store_file(self, file_path: str, content: str) -> int:
        """
        Store file content with embeddings.
        
        Chunks file and creates embedding for each chunk.
        """
        chunks = chunk_text(content)
        embeddings_data = []
        
        for chunk_text_item, start, end in chunks:
            embedding = self.model.embed(chunk_text_item)
            if embedding:
                embeddings_data.append((file_path, start, end, embedding))
        
        if embeddings_data:
            count = self.store.store_batch(embeddings_data)
            info(f"Long-term memory: stored {count} chunks from {file_path}")
            return count
        return 0
    
    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Search for similar content.
        
        Returns files/chunks similar to query.
        """
        query_embedding = self.model.embed(query)
        if not query_embedding:
            return []
        
        return self.store.search(query_embedding, limit)
    
    def get_file_embeddings(self, file_path: str) -> List[Dict]:
        """Get all embeddings for a file."""
        return self.store.get_by_file(file_path)
    
    def remove_file(self, file_path: str) -> int:
        """Remove all embeddings for a file."""
        return self.store.delete_by_file(file_path)
    
    def count(self) -> int:
        """Get total embeddings count."""
        return self.store.count()
    
    def status(self) -> dict:
        """Get long-term memory status."""
        return {
            "embeddings": self.count(),
            "model_loaded": self.model.is_loaded(),
        }


class EpisodicMemory:
    """
    Episodic memory - log of actions taken.
    
    Append-only log for "what did I do last week?"
    Stored in SQLite via state store.
    """
    
    def __init__(self):
        self.state = get_state_store()
    
    def log(self, action: str, details: str = None):
        """Log an action."""
        self.state.log_action(action, details)
    
    def get_recent(self, limit: int = 50) -> List[Dict]:
        """Get recent actions."""
        return self.state.get_recent_actions(limit)
    
    def get_since(self, timestamp: int) -> List[Dict]:
        """Get actions since timestamp."""
        return self.state.get_actions_since(timestamp)
    
    def count(self) -> int:
        """Get total actions count."""
        # Approximate - would need separate count query
        return len(self.get_recent(1000))
    
    def status(self) -> dict:
        """Get episodic memory status."""
        return {
            "recent_actions": len(self.get_recent(10)),
        }


class Memory:
    """
    Unified hierarchical memory system.
    
    Combines all four memory tiers:
    - Working: currently edited files
    - Project: key project files
    - Long-term: semantic embeddings
    - Episodic: action log
    """
    
    def __init__(self):
        self.working = WorkingMemory()
        self.project = ProjectMemory()
        self.longterm = LongTermMemory()
        self.episodic = EpisodicMemory()
        self._turn = 0
    
    def tick(self):
        """
        Increment turn and perform maintenance.
        
        Call after each task completes.
        """
        self._turn += 1
        self.working.tick()
        
        # Log turn in episodic memory
        self.episodic.log("tick", f"Turn {self._turn}")
    
    def add_to_working(self, file_path: str, content: str, tokens: int):
        """Add file to working memory."""
        self.working.add(file_path, content, tokens)
    
    def add_to_project(self, file_path: str, content: str, is_protected: bool = False):
        """Add file to project memory."""
        self.project.add(file_path, content, is_protected)
    
    def store_in_longterm(self, file_path: str, content: str):
        """Store file in long-term memory with embeddings."""
        self.longterm.store_file(file_path, content)
    
    def log_action(self, action: str, details: str = None):
        """Log action in episodic memory."""
        self.episodic.log(action, details)
    
    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Search long-term memory."""
        return self.longterm.search(query, limit)
    
    def get_working_content(self) -> Dict[str, str]:
        """Get all working memory content."""
        return self.working.get_all()
    
    def clear_working(self):
        """Clear working memory (after task)."""
        self.working.clear()
    
    def status(self) -> dict:
        """Get complete memory status."""
        return {
            "turn": self._turn,
            "working": self.working.status(),
            "project": self.project.status(),
            "longterm": self.longterm.status(),
            "episodic": self.episodic.status(),
        }


# Global memory instance
_memory: Optional[Memory] = None


def get_memory() -> Memory:
    """Get the global memory instance."""
    global _memory
    if _memory is None:
        _memory = Memory()
    return _memory


def reset_memory():
    """Reset global memory (for testing)."""
    global _memory
    if _memory:
        _memory = None
