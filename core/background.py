#!/usr/bin/env python3
"""
Background Task Execution for Codey-v2.

Supports:
- Async background tasks
- File watches with watchdog
- Periodic tasks
- Task lifecycle management
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, Callable, Any, List, Dict
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import info, warning, error, success


class BackgroundTaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BackgroundTask:
    """Represents a background task."""
    id: str
    name: str
    func: Callable
    status: BackgroundTaskStatus = BackgroundTaskStatus.PENDING
    started_at: Optional[float] = None
    stopped_at: Optional[float] = None
    timeout: float = 1800  # 30 minutes default
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    _asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)
    
    def is_running(self) -> bool:
        """Check if task is currently running."""
        return self.status == BackgroundTaskStatus.RUNNING
    
    def runtime(self) -> float:
        """Get current runtime in seconds."""
        if not self.started_at:
            return 0
        end = self.stopped_at or time.time()
        return end - self.started_at
    
    def is_timed_out(self) -> bool:
        """Check if task has exceeded timeout."""
        return self.runtime() > self.timeout


class BackgroundTaskManager:
    """
    Manages background tasks for Codey-v2.
    
    Features:
    - Start/stop tasks
    - Timeout enforcement
    - Resource tracking
    - File watch integration
    """
    
    def __init__(self):
        self._tasks: Dict[str, BackgroundTask] = {}
        self._running: bool = False
        self._task_counter: int = 0
    
    def _generate_id(self) -> str:
        """Generate unique task ID."""
        self._task_counter += 1
        return f"bg_{self._task_counter}_{int(time.time())}"
    
    def add_task(self, name: str, func: Callable, 
                 timeout: float = 1800, **metadata) -> str:
        """
        Add a background task.
        
        Args:
            name: Task name
            func: Async function to run
            timeout: Maximum runtime in seconds
            **metadata: Additional task metadata
            
        Returns:
            Task ID
        """
        task_id = self._generate_id()
        task = BackgroundTask(
            id=task_id,
            name=name,
            func=func,
            timeout=timeout,
            metadata=metadata,
        )
        self._tasks[task_id] = task
        info(f"Background: added task '{name}' (ID: {task_id})")
        return task_id
    
    async def start_task(self, task_id: str) -> bool:
        """
        Start a background task.
        
        Args:
            task_id: Task ID to start
            
        Returns:
            True if started successfully
        """
        task = self._tasks.get(task_id)
        if not task:
            error(f"Background: task {task_id} not found")
            return False
        
        if task.status != BackgroundTaskStatus.PENDING:
            warning(f"Background: task {task_id} is not pending")
            return False
        
        task.status = BackgroundTaskStatus.RUNNING
        task.started_at = time.time()

        info(f"Background: starting task '{task.name}'")

        # Store asyncio.Task handle so stop_task() can cancel it
        task._asyncio_task = asyncio.create_task(self._run_task(task))

        return True
    
    async def _run_task(self, task: BackgroundTask):
        """Execute a background task with timeout and error handling."""
        try:
            # Run the task function
            if asyncio.iscoroutinefunction(task.func):
                await asyncio.wait_for(task.func(), timeout=task.timeout)
            else:
                # Run sync function in executor
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, task.func)
            
            task.status = BackgroundTaskStatus.COMPLETED
            task.stopped_at = time.time()
            success(f"Background: completed task '{task.name}'")
            
        except asyncio.TimeoutError:
            task.status = BackgroundTaskStatus.FAILED
            task.error = f"Timeout after {task.timeout}s"
            error(f"Background: task '{task.name}' timed out")
            
        except asyncio.CancelledError:
            task.status = BackgroundTaskStatus.STOPPED
            task.stopped_at = time.time()
            info(f"Background: stopped task '{task.name}'")
            
        except Exception as e:
            task.status = BackgroundTaskStatus.FAILED
            task.error = str(e)
            task.stopped_at = time.time()
            error(f"Background: task '{task.name}' failed: {e}")
    
    def stop_task(self, task_id: str) -> bool:
        """
        Stop a background task.
        
        Args:
            task_id: Task ID to stop
            
        Returns:
            True if stopped successfully
        """
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if not task.is_running():
            return False
        
        task.status = BackgroundTaskStatus.STOPPING
        info(f"Background: stopping task '{task.name}'")

        # Cancel the underlying asyncio.Task — _run_task catches CancelledError
        # and sets status to STOPPED with a timestamp.
        if task._asyncio_task and not task._asyncio_task.done():
            task._asyncio_task.cancel()

        return True
    
    def get_task(self, task_id: str) -> Optional[BackgroundTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def get_running_tasks(self) -> List[BackgroundTask]:
        """Get all running tasks."""
        return [t for t in self._tasks.values() if t.is_running()]
    
    def get_all_tasks(self) -> List[BackgroundTask]:
        """Get all tasks."""
        return list(self._tasks.values())
    
    def cleanup_completed(self, max_age: float = 3600) -> int:
        """
        Remove completed/failed tasks older than max_age seconds.
        
        Returns:
            Number of tasks removed
        """
        now = time.time()
        to_remove = []
        
        for task_id, task in self._tasks.items():
            if task.status in (BackgroundTaskStatus.COMPLETED, 
                               BackgroundTaskStatus.FAILED,
                               BackgroundTaskStatus.STOPPED):
                if task.stopped_at and (now - task.stopped_at) > max_age:
                    to_remove.append(task_id)
        
        for task_id in to_remove:
            del self._tasks[task_id]
        
        if to_remove:
            info(f"Background: cleaned up {len(to_remove)} completed tasks")
        
        return len(to_remove)
    
    def status(self) -> dict:
        """Get background task manager status."""
        tasks = self.get_all_tasks()
        return {
            "total": len(tasks),
            "running": len(self.get_running_tasks()),
            "pending": len([t for t in tasks if t.status == BackgroundTaskStatus.PENDING]),
            "completed": len([t for t in tasks if t.status == BackgroundTaskStatus.COMPLETED]),
            "failed": len([t for t in tasks if t.status == BackgroundTaskStatus.FAILED]),
        }


class FileWatchManager:
    """
    Manages file system watches using watchdog.
    
    Features:
    - Watch files/directories for changes
    - Callback on file events
    - Debouncing to avoid excessive triggers
    """
    def __init__(self):
        self._watches: Dict[str, dict] = {}
        self._observer = None
        self._running = False
    
    def start(self):
        """Start the file watch observer."""
        try:
            from watchdog.observers import Observer
            self._observer = Observer()
            self._observer.start()
            self._running = True
            info("FileWatch: observer started")
        except ImportError:
            warning("FileWatch: watchdog not installed, file watches disabled")
        except Exception as e:
            error(f"FileWatch: failed to start observer: {e}")
    
    def stop(self):
        """Stop the file watch observer."""
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join()
            self._running = False
            info("FileWatch: observer stopped")
    
    def add_watch(self, path: str, callback: Callable, 
                  patterns: List[str] = None,
                  recursive: bool = True) -> str:
        """
        Add a file watch.
        
        Args:
            path: Path to watch
            callback: Function to call on events
            patterns: File patterns to watch (e.g., ['*.py'])
            recursive: Watch subdirectories
            
        Returns:
            Watch ID
        """
        watch_id = f"watch_{path}_{int(time.time())}"
        
        self._watches[watch_id] = {
            "path": path,
            "callback": callback,
            "patterns": patterns,
            "recursive": recursive,
        }
        
        if self._observer and self._running:
            try:
                from watchdog.observers import Observer
                from watchdog.events import FileSystemEventHandler
                
                class WatchHandler(FileSystemEventHandler):
                    def __init__(self, cb, pats):
                        self.callback = cb
                        self.patterns = pats
                        self._last_trigger = 0
                        self._debounce = 0.5  # 500ms debounce
                    
                    def _should_trigger(self, path: str) -> bool:
                        if not self.patterns:
                            return True
                        return any(Path(path).match(p) for p in self.patterns)
                    
                    def _debounced_callback(self, event):
                        now = time.time()
                        if now - self._last_trigger < self._debounce:
                            return
                        self._last_trigger = now
                        try:
                            self.callback(event.event_type, event.src_path)
                        except Exception as e:
                            error(f"FileWatch: callback error: {e}")
                    
                    def on_modified(self, event):
                        if not event.is_directory and self._should_trigger(event.src_path):
                            self._debounced_callback(event)
                    
                    def on_created(self, event):
                        if not event.is_directory and self._should_trigger(event.src_path):
                            self._debounced_callback(event)
                    
                    def on_deleted(self, event):
                        if not event.is_directory and self._should_trigger(event.src_path):
                            self._debounced_callback(event)
                
                watch_path = Path(path)
                if not watch_path.exists():
                    watch_path.mkdir(parents=True, exist_ok=True)
                
                handler = WatchHandler(callback, patterns)
                self._observer.schedule(handler, str(watch_path), recursive=recursive)
                
                info(f"FileWatch: added watch on {path}")
                
            except Exception as e:
                error(f"FileWatch: failed to add watch: {e}")
        
        return watch_id
    
    def remove_watch(self, watch_id: str) -> bool:
        """Remove a file watch."""
        if watch_id in self._watches:
            del self._watches[watch_id]
            info(f"FileWatch: removed watch {watch_id}")
            return True
        return False
    
    def status(self) -> dict:
        """Get file watch status."""
        return {
            "running": self._running,
            "watches": len(self._watches),
        }


# Global instances
_background_manager: Optional[BackgroundTaskManager] = None
_file_watch_manager: Optional[FileWatchManager] = None


def get_background_manager() -> BackgroundTaskManager:
    """Get the global background task manager."""
    global _background_manager
    if _background_manager is None:
        _background_manager = BackgroundTaskManager()
    return _background_manager


def get_file_watch_manager() -> FileWatchManager:
    """Get the global file watch manager."""
    global _file_watch_manager
    if _file_watch_manager is None:
        _file_watch_manager = FileWatchManager()
    return _file_watch_manager


def reset_background():
    """Reset global instances (for testing)."""
    global _background_manager, _file_watch_manager
    _background_manager = None
    _file_watch_manager = None
