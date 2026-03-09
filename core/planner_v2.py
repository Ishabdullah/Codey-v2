#!/usr/bin/env python3
"""
Internal Planner for Codey-v2.

Native task planning (no model-asked orchestration):
- Task queue with dependency tracking
- Automatic task breakdown for complex tasks
- Adaptation on failure (retry with different approach)
- Background task scheduling
"""

import time
import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import info, warning, error, success
from core.state import get_state_store


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"  # Waiting on dependencies


@dataclass
class Task:
    """Represents a planned task."""
    id: int
    description: str
    status: TaskStatus
    dependencies: List[int] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: int = 0
    started_at: Optional[int] = None
    completed_at: Optional[int] = None
    retry_count: int = 0
    max_retries: int = 3


class Planner:
    """
    Internal task planner for Codey-v2.

    Features:
    - Task queue with dependencies
    - Automatic task breakdown
    - Adaptation on failure
    - Persistence in SQLite
    """
    
    def __init__(self, max_retries: int = 3):
        self.state = get_state_store()
        self.max_retries = max_retries
        self._tasks: Dict[int, Task] = {}
        self._running: bool = False
        self._current_task: Optional[Task] = None
        self._adaptation_callbacks: Dict[str, Callable] = {}
        
        # Load existing tasks from database
        self._load_tasks()
    
    def _load_tasks(self):
        """Load pending/running tasks from database."""
        tasks = self.state.get_all_tasks()
        for t in tasks:
            if t["status"] in ("pending", "running"):
                deps = []
                if t.get("dependencies"):
                    try:
                        deps = json.loads(t["dependencies"])
                    except:
                        deps = []
                
                self._tasks[t["id"]] = Task(
                    id=t["id"],
                    description=t["description"],
                    status=TaskStatus(t["status"]),
                    dependencies=deps,
                    result=t.get("result"),
                    created_at=t.get("created_at", 0),
                    started_at=t.get("started_at"),
                    completed_at=t.get("completed_at"),
                    retry_count=t.get("retry_count", 0),
                )
    
    def add_task(self, description: str, dependencies: List[int] = None) -> int:
        """
        Add a new task to the queue.
        
        Args:
            description: Task description
            dependencies: List of task IDs that must complete first
            
        Returns:
            Task ID
        """
        # Add to database
        task_id = self.state.add_task(description)
        
        # Update with dependencies if any
        if dependencies:
            self._update_task_dependencies(task_id, dependencies)
        
        # Create local task object
        task = Task(
            id=task_id,
            description=description,
            status=TaskStatus.PENDING,
            dependencies=dependencies or [],
            created_at=int(time.time()),
        )
        self._tasks[task_id] = task
        
        info(f"Planner: added task {task_id}: {description[:50]}...")
        
        # Log in episodic memory
        self.state.log_action("task_planned", description[:200])
        
        return task_id
    
    def add_tasks(self, descriptions: List[str]) -> List[int]:
        """
        Add multiple tasks with sequential dependencies.
        
        Each task depends on the previous one.
        
        Args:
            descriptions: List of task descriptions
            
        Returns:
            List of task IDs
        """
        task_ids = []
        prev_id = None
        
        for desc in descriptions:
            deps = [prev_id] if prev_id else []
            task_id = self.add_task(desc, dependencies=deps)
            task_ids.append(task_id)
            prev_id = task_id
        
        return task_ids
    
    def _update_task_dependencies(self, task_id: int, dependencies: List[int]):
        """Update task dependencies in database."""
        import json
        self.state.execute(
            "UPDATE task_queue SET dependencies = ? WHERE id = ?",
            (json.dumps(dependencies), task_id),
        )
    
    def get_next_task(self) -> Optional[Task]:
        """
        Get the next task ready to execute.
        
        Returns task with:
        - Status = pending
        - All dependencies completed
        
        Returns None if no task ready.
        """
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            
            # Check dependencies
            if not self._dependencies_met(task):
                continue
            
            return task
        
        return None
    
    def _dependencies_met(self, task: Task) -> bool:
        """Check if all task dependencies are completed."""
        for dep_id in task.dependencies:
            dep_task = self._tasks.get(dep_id)
            if not dep_task or dep_task.status != TaskStatus.DONE:
                return False
        return True
    
    def start_task(self, task_id: int) -> bool:
        """Mark a task as running."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        task.status = TaskStatus.RUNNING
        task.started_at = int(time.time())
        self._current_task = task
        
        # Update database
        self.state.start_task(task_id)
        
        info(f"Planner: started task {task_id}")
        return True
    
    def complete_task(self, task_id: int, result: str) -> bool:
        """Mark a task as completed."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        task.status = TaskStatus.DONE
        task.result = result
        task.completed_at = int(time.time())
        
        # Update database
        self.state.complete_task(task_id, result)
        
        success(f"Planner: completed task {task_id}")
        
        # Log in episodic memory
        self.state.log_action("task_completed", f"Task {task_id}: {result[:100]}")
        
        # Clear current task if this was it
        if self._current_task and self._current_task.id == task_id:
            self._current_task = None
        
        return True
    
    def fail_task(self, task_id: int, error_msg: str) -> bool:
        """
        Mark a task as failed, with retry logic.

        If retries remain, sets task back to pending.
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        task.retry_count += 1
        self.state.increment_retry(task_id)

        if task.retry_count < self.max_retries:
            # Retry - set back to pending
            task.status = TaskStatus.PENDING
            task.error = f"Retry {task.retry_count}/{self.max_retries}: {error_msg}"
            self.state.execute(
                "UPDATE task_queue SET status = 'pending' WHERE id = ?", (task_id,)
            )
            warning(f"Planner: task {task_id} failed, retrying ({task.retry_count}/{self.max_retries})")
        else:
            # Max retries reached - mark as failed
            task.status = TaskStatus.FAILED
            task.error = error_msg
            task.completed_at = int(time.time())

            # Update database
            self.state.fail_task(task_id, error_msg)

            error(f"Planner: task {task_id} failed permanently: {error_msg}")

            # Log in episodic memory
            self.state.log_action("task_failed", f"Task {task_id}: {error_msg[:200]}")

        # Clear current task
        if self._current_task and self._current_task.id == task_id:
            self._current_task = None

        return True

    def adapt(self, task_id: int, error_msg: str) -> Optional[str]:
        """
        Adapt strategy on failure.
        
        Called when a task fails. Can suggest alternative approaches.
        
        Args:
            task_id: Failed task ID
            error: Error message
            
        Returns:
            Suggested alternative approach, or None
        """
        task = self._tasks.get(task_id)
        if not task:
            return None
        
        # Check for registered adaptation callbacks
        for pattern, callback in self._adaptation_callbacks.items():
            if pattern in error_msg.lower():
                return callback(task, error_msg)

        # Default adaptations
        if "write" in error_msg.lower() or "permission" in error_msg.lower():
            return "Try using patch instead of write"
        elif "not found" in error_msg.lower() or "exists" in error_msg.lower():
            return "Create the file/directory first"
        elif "syntax" in error_msg.lower() or "error" in error_msg.lower():
            return "Debug with smaller test case first"
        
        return None
    
    def register_adaptation(self, error_pattern: str, callback: Callable):
        """
        Register a callback for adapting to specific errors.
        
        Args:
            error_pattern: Pattern to match in error message
            callback: Function(task, error) -> suggested alternative
        """
        self._adaptation_callbacks[error_pattern] = callback
    
    def get_blocked_tasks(self) -> List[Task]:
        """Get tasks blocked by incomplete dependencies."""
        blocked = []
        for task in self._tasks.values():
            if task.status == TaskStatus.PENDING and not self._dependencies_met(task):
                blocked.append(task)
        return blocked
    
    def get_pending_tasks(self) -> List[Task]:
        """Get all pending tasks."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]
    
    def get_running_tasks(self) -> List[Task]:
        """Get all running tasks."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.RUNNING]
    
    def get_completed_tasks(self) -> List[Task]:
        """Get all completed tasks."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.DONE]
    
    def get_failed_tasks(self) -> List[Task]:
        """Get all failed tasks."""
        return [t for t in self._tasks.values() if t.status == TaskStatus.FAILED]
    
    def get_current_task(self) -> Optional[Task]:
        """Get the currently executing task."""
        return self._current_task
    
    def cancel_task(self, task_id: int) -> bool:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.status in (TaskStatus.DONE, TaskStatus.FAILED):
            return False
        
        task.status = TaskStatus.FAILED
        task.error = "Cancelled by user"
        task.completed_at = int(time.time())
        
        # Use state's cancel method
        self.state.cancel_task(task_id)
        
        info(f"Planner: cancelled task {task_id}")
        return True
    
    def clear_completed(self):
        """Clear completed and failed tasks from memory."""
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t.status in (TaskStatus.DONE, TaskStatus.FAILED)
        ]
        for tid in to_remove:
            del self._tasks[tid]
        info(f"Planner: cleared {len(to_remove)} completed tasks")
    
    def status(self) -> dict:
        """Get planner status."""
        return {
            "total": len(self._tasks),
            "pending": len(self.get_pending_tasks()),
            "running": len(self.get_running_tasks()),
            "done": len(self.get_completed_tasks()),
            "failed": len(self.get_failed_tasks()),
            "blocked": len(self.get_blocked_tasks()),
            "current": self._current_task.id if self._current_task else None,
        }
    
    def breakdown_complex_task(self, description: str) -> List[str]:
        """
        Break down a complex task into subtasks.
        
        This is a simple heuristic-based breakdown.
        For production, would use LLM to generate tasks.
        
        Args:
            description: Complex task description
            
        Returns:
            List of subtask descriptions
        """
        subtasks = []
        desc_lower = description.lower()
        
        # Pattern matching for common task types
        if "build" in desc_lower or "create" in desc_lower:
            if "app" in desc_lower or "api" in desc_lower:
                subtasks = [
                    "Set up project structure and dependencies",
                    "Create main application file",
                    "Implement core functionality",
                    "Add error handling",
                    "Write tests",
                    "Run tests and fix any failures",
                ]
            elif "file" in desc_lower or "script" in desc_lower:
                subtasks = [
                    "Create the file with basic structure",
                    "Implement main functionality",
                    "Test the file works correctly",
                ]
        
        if "fix" in desc_lower or "debug" in desc_lower:
            subtasks = [
                "Identify the error/bug",
                "Understand the root cause",
                "Implement the fix",
                "Test the fix works",
            ]
        
        if "test" in desc_lower:
            subtasks = [
                "Understand what needs testing",
                "Write test file/cases",
                "Run tests",
                "Fix any failing tests",
            ]
        
        # Default breakdown if no pattern matched
        if not subtasks:
            subtasks = [
                f"Analyze: {description}",
                f"Plan approach for: {description}",
                f"Implement: {description}",
                f"Test: {description}",
            ]
        
        return subtasks


# Global planner instance
_planner: Optional[Planner] = None


def get_planner() -> Planner:
    """Get the global planner instance."""
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner


def reset_planner():
    """Reset global planner (for testing)."""
    global _planner
    if _planner:
        _planner = None
