#!/usr/bin/env python3
"""
Direct filesystem access for Codey-v2.

Provides a class-based interface for file operations:
- read(path) - Read file content
- write(path, content) - Write file with confirmation
- patch(path, old, new) - Patch file with diff tracking
- exists(path) - Check if path exists
- list_dir(path) - List directory contents

Removes need for JSON tool-call parsing. Agent calls methods directly.
"""

import os
import difflib
from pathlib import Path
from typing import List, Optional, Union

from utils.logger import info, warning, error, success
from utils.config import WORKSPACE_ROOT, CODE_DIR
from core.filehistory import snapshot as _snapshot


class FilesystemAccessError(Exception):
    """Raised when filesystem access is denied or fails."""
    pass


class Filesystem:
    """
    Direct filesystem access for Codey-v2 agent.
    
    Provides safe file operations with:
    - Path validation (no access outside workspace)
    - Workspace checks (prevent writing to protected areas)
    - Diff tracking for patches
    - Error handling with descriptive messages
    """
    
    def __init__(self, workspace: Path = None):
        """
        Initialize filesystem access.
        
        Args:
            workspace: Root directory for file operations.
                      Defaults to current working directory.
        """
        self.workspace = workspace or WORKSPACE_ROOT
        self._last_diff: Optional[str] = None
    
    def _validate_path(self, path: Union[str, Path]) -> Path:
        """
        Validate and resolve path.
        
        Ensures path is within workspace and exists (for read operations).
        
        Args:
            path: Path to validate
            
        Returns:
            Resolved Path object
            
        Raises:
            FilesystemAccessError: If path is invalid or outside workspace
        """
        if isinstance(path, str):
            path = Path(path)
        
        # Resolve to absolute path
        if not path.is_absolute():
            path = self.workspace / path
        
        path = path.resolve()
        
        # Check if path is within workspace
        try:
            path.relative_to(self.workspace)
        except ValueError:
            # Allow access to CODE_DIR for self-modification
            try:
                path.relative_to(CODE_DIR)
            except ValueError:
                raise FilesystemAccessError(
                    f"Access denied: {path} is outside workspace ({self.workspace})"
                )
        
        return path
    
    def read(self, path: Union[str, Path]) -> str:
        """
        Read file content.
        
        Args:
            path: Path to file (relative to workspace or absolute)
            
        Returns:
            File content as string
            
        Raises:
            FilesystemAccessError: If file cannot be read
        """
        try:
            path = self._validate_path(path)
            
            if not path.exists():
                raise FilesystemAccessError(f"File not found: {path}")
            
            if not path.is_file():
                raise FilesystemAccessError(f"Not a file: {path}")
            
            content = path.read_text(encoding='utf-8')
            try:
                rel = path.relative_to(self.workspace)
            except ValueError:
                rel = path
            info(f"Read {rel} ({len(content)} chars)")
            return content
            
        except FilesystemAccessError:
            raise
        except Exception as e:
            raise FilesystemAccessError(f"Failed to read {path}: {e}")
    
    def write(self, path: Union[str, Path], content: str) -> str:
        """
        Write file content.
        
        Creates parent directories if they don't exist.
        
        Args:
            path: Path to file (relative to workspace or absolute)
            content: Content to write
            
        Returns:
            Success message with file path
            
        Raises:
            FilesystemAccessError: If file cannot be written
        """
        try:
            path = self._validate_path(path)
            
            # Check if modifying Codey's own code (for potential rollback)
            is_core_file = False
            try:
                path.relative_to(CODE_DIR)
                is_core_file = True
                info(f"Writing to core Codey file: {path}")
            except ValueError:
                pass
            
            # Create parent directories
            path.parent.mkdir(parents=True, exist_ok=True)

            # Snapshot existing file so /undo works for write_file too
            if path.exists():
                _snapshot(str(path))

            # Write content
            path.write_text(content, encoding='utf-8')

            try:
                rel = path.relative_to(self.workspace)
            except ValueError:
                rel = path
            msg = f"Written {rel}"
            success(msg)
            return msg
            
        except FilesystemAccessError:
            raise
        except Exception as e:
            raise FilesystemAccessError(f"Failed to write {path}: {e}")
    
    def patch(self, path: Union[str, Path], old_str: str, new_str: str) -> str:
        """
        Patch file content (replace old_str with new_str).
        
        Args:
            path: Path to file
            old_str: String to find and replace
            new_str: Replacement string
            
        Returns:
            Diff of changes made
            
        Raises:
            FilesystemAccessError: If patch cannot be applied
        """
        try:
            path = self._validate_path(path)
            
            if not path.exists():
                raise FilesystemAccessError(f"File not found: {path}")
            
            # Read current content
            content = path.read_text(encoding='utf-8')
            
            # Find and replace
            if old_str not in content:
                raise FilesystemAccessError(
                    f"Could not find specified string in {path}"
                )
            
            new_content = content.replace(old_str, new_str, 1)
            
            # Generate diff
            diff = self._generate_diff(
                path.name,
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True)
            )
            self._last_diff = diff
            
            # Write new content
            path.write_text(new_content, encoding='utf-8')

            try:
                rel = path.relative_to(self.workspace)
            except ValueError:
                rel = path
            msg = f"Patched {rel}"
            success(msg)
            return diff
            
        except FilesystemAccessError:
            raise
        except Exception as e:
            raise FilesystemAccessError(f"Failed to patch {path}: {e}")
    
    def append(self, path: Union[str, Path], content: str) -> str:
        """
        Append content to file.
        
        Args:
            path: Path to file
            content: Content to append
            
        Returns:
            Success message
            
        Raises:
            FilesystemAccessError: If append fails
        """
        try:
            path = self._validate_path(path)
            
            # Create if doesn't exist
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
                try:
                    rel = path.relative_to(self.workspace)
                except ValueError:
                    rel = path
                return f"Created {rel}"

            # Append to existing file
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)

            try:
                rel = path.relative_to(self.workspace)
            except ValueError:
                rel = path
            msg = f"Appended to {rel}"
            success(msg)
            return msg
            
        except FilesystemAccessError:
            raise
        except Exception as e:
            raise FilesystemAccessError(f"Failed to append to {path}: {e}")
    
    def exists(self, path: Union[str, Path]) -> bool:
        """
        Check if path exists.
        
        Args:
            path: Path to check
            
        Returns:
            True if path exists, False otherwise
        """
        try:
            path = self._validate_path(path)
            return path.exists()
        except FilesystemAccessError:
            return False
    
    def is_file(self, path: Union[str, Path]) -> bool:
        """
        Check if path is a file.
        
        Args:
            path: Path to check
            
        Returns:
            True if path is a file, False otherwise
        """
        try:
            path = self._validate_path(path)
            return path.is_file()
        except FilesystemAccessError:
            return False
    
    def is_dir(self, path: Union[str, Path]) -> bool:
        """
        Check if path is a directory.
        
        Args:
            path: Path to check
            
        Returns:
            True if path is a directory, False otherwise
        """
        try:
            path = self._validate_path(path)
            return path.is_dir()
        except FilesystemAccessError:
            return False
    
    def list_dir(self, path: Union[str, Path] = ".") -> List[str]:
        """
        List directory contents.
        
        Args:
            path: Directory path (default: workspace root)
            
        Returns:
            List of file/directory names
            
        Raises:
            FilesystemAccessError: If directory cannot be listed
        """
        try:
            path = self._validate_path(path)
            
            if not path.is_dir():
                raise FilesystemAccessError(f"Not a directory: {path}")
            
            entries = [e.name for e in path.iterdir()]
            entries.sort()

            try:
                rel = path.relative_to(self.workspace)
            except ValueError:
                rel = path
            info(f"Listed {rel} ({len(entries)} entries)")
            return entries
            
        except FilesystemAccessError:
            raise
        except Exception as e:
            raise FilesystemAccessError(f"Failed to list {path}: {e}")
    
    def _generate_diff(self, filename: str, old_lines: List[str], new_lines: List[str]) -> str:
        """Generate unified diff between old and new content."""
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3
        )
        return ''.join(diff)
    
    def get_last_diff(self) -> Optional[str]:
        """Get the diff from the last patch operation."""
        return self._last_diff


# Global filesystem instance
_filesystem: Optional[Filesystem] = None


def get_filesystem(workspace: Path = None) -> Filesystem:
    """Get the global filesystem instance."""
    global _filesystem
    if _filesystem is None:
        _filesystem = Filesystem(workspace)
    return _filesystem


def reset_filesystem():
    """Reset the global filesystem instance (for testing)."""
    global _filesystem
    if _filesystem:
        _filesystem = None
