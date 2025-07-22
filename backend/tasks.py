"""
Asynchronous task processing for long-running operations.

This module provides an asynchronous task queue system for processing
long-running operations like testing, linting, and other resource-intensive tasks.
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Callable
import threading
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from datetime import datetime

from .config import settings
from . import database

# Configure logger
logger = logging.getLogger(__name__)

class TaskStatus(str, Enum):
    """Status for asynchronous tasks."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

class Task:
    """Represents an asynchronous task."""
    
    def __init__(self, task_id: str, task_type: str, user_id: str = "anonymous"):
        """Initialize a task.
        
        Args:
            task_id: Unique ID for the task
            task_type: Type of task (e.g., "test", "lint")
            user_id: ID of the user who initiated the task
        """
        self.task_id = task_id
        self.task_type = task_type
        self.user_id = user_id
        self.status = TaskStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None
        self.created_at = datetime.utcnow().isoformat()
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.progress: int = 0
        self.details: Dict[str, Any] = {}
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to a dictionary."""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "user_id": self.user_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress": self.progress,
            "details": self.details,
            "has_result": self.result is not None,
            "has_error": self.error is not None,
        }
        
    def __str__(self) -> str:
        return f"Task({self.task_id}, {self.task_type}, {self.status})"

class TaskQueue:
    """Task queue for managing asynchronous tasks."""
    
    def __init__(self, max_workers: int = 4):
        """Initialize the task queue.
        
        Args:
            max_workers: Maximum number of worker threads
        """
        self.tasks: Dict[str, Task] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.RLock()
        
    def create_task(self, task_type: str, user_id: str = "anonymous") -> Task:
        """Create a new task.
        
        Args:
            task_type: Type of task
            user_id: ID of the user who initiated the task
            
        Returns:
            Created task
        """
        task_id = str(uuid.uuid4())
        with self.lock:
            task = Task(task_id, task_type, user_id)
            self.tasks[task_id] = task
            
            # Record task creation in telemetry
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "task_created",
                    {"task_id": task_id, "task_type": task_type},
                    user_id=user_id
                )
                
            return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        with self.lock:
            return self.tasks.get(task_id)
    
    def list_tasks(self, user_id: Optional[str] = None, limit: int = 100) -> List[Task]:
        """List tasks, optionally filtered by user ID."""
        with self.lock:
            if user_id:
                filtered = [t for t in self.tasks.values() if t.user_id == user_id]
            else:
                filtered = list(self.tasks.values())
                
            # Sort by creation time (newest first) and limit results
            return sorted(filtered, key=lambda t: t.created_at, reverse=True)[:limit]
    
    def submit(self, 
               task_id: str, 
               func: Callable[..., Any], 
               *args: Any, 
               **kwargs: Any) -> None:
        """Submit a task for execution.
        
        Args:
            task_id: ID of the task to execute
            func: Function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
        """
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return
                
            if task.status != TaskStatus.PENDING:
                logger.warning(f"Task {task_id} is already {task.status}")
                return
                
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.utcnow().isoformat()
            
        # Submit the task to the executor
        self.executor.submit(self._execute_task, task, func, *args, **kwargs)
        
        logger.info(f"Submitted task {task_id} ({task.task_type})")
    
    def _execute_task(self, task: Task, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Execute a task in a worker thread."""
        try:
            # Record task start in telemetry
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "task_started",
                    {"task_id": task.task_id, "task_type": task.task_type},
                    user_id=task.user_id
                )
                
            # Execute the task function
            result = func(*args, **kwargs)
            
            # Update task status
            with self.lock:
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = datetime.utcnow().isoformat()
                task.progress = 100
            
            logger.info(f"Task {task.task_id} completed successfully")
            
            # Record task completion in telemetry
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "task_completed",
                    {
                        "task_id": task.task_id, 
                        "task_type": task.task_type,
                        "duration_ms": self._calculate_duration_ms(task)
                    },
                    user_id=task.user_id
                )
                
        except Exception as e:
            logger.exception(f"Task {task.task_id} failed: {e}")
            
            # Update task status
            with self.lock:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = datetime.utcnow().isoformat()
            
            # Record task failure in telemetry
            if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "task_failed",
                    {
                        "task_id": task.task_id, 
                        "task_type": task.task_type,
                        "error": str(e),
                        "duration_ms": self._calculate_duration_ms(task)
                    },
                    user_id=task.user_id
                )
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task if it's still pending."""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return False
                
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELED
                task.completed_at = datetime.utcnow().isoformat()
                
                # Record task cancellation in telemetry
                if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
                    database.record_telemetry(
                        "task_canceled",
                        {"task_id": task_id, "task_type": task.task_type},
                        user_id=task.user_id
                    )
                    
                logger.info(f"Task {task_id} canceled")
                return True
            else:
                logger.warning(f"Cannot cancel task {task_id}: already {task.status}")
                return False
    
    def update_progress(self, task_id: str, progress: int, details: Optional[Dict[str, Any]] = None) -> bool:
        """Update the progress of a task."""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return False
                
            if task.status != TaskStatus.RUNNING:
                logger.warning(f"Cannot update progress: task {task_id} is {task.status}")
                return False
                
            task.progress = min(max(0, progress), 100)  # Ensure progress is between 0-100
            
            if details:
                task.details.update(details)
                
            return True
    
    def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """Clean up completed tasks older than the specified age."""
        now = datetime.utcnow()
        cutoff = now.timestamp() - (max_age_hours * 3600)
        
        to_remove = []
        
        with self.lock:
            for task_id, task in self.tasks.items():
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED):
                    completed_at = datetime.fromisoformat(task.completed_at or task.created_at)
                    if completed_at.timestamp() < cutoff:
                        to_remove.append(task_id)
            
            # Remove identified tasks
            for task_id in to_remove:
                del self.tasks[task_id]
                
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks")
            
        return len(to_remove)
    
    def _calculate_duration_ms(self, task: Task) -> int:
        """Calculate task duration in milliseconds."""
        if not task.started_at:
            return 0
            
        start_time = datetime.fromisoformat(task.started_at)
        end_time = datetime.fromisoformat(task.completed_at or datetime.utcnow().isoformat())
        
        return int((end_time - start_time).total_seconds() * 1000)

# Global task queue instance
_task_queue: Optional[TaskQueue] = None

def get_task_queue() -> TaskQueue:
    """Get the global task queue instance."""
    global _task_queue
    if _task_queue is None:
        # Configure max workers based on settings or default
        max_workers = getattr(settings, "TASK_MAX_WORKERS", 4)
        _task_queue = TaskQueue(max_workers=max_workers)
        
        # Start cleanup thread
        threading.Thread(target=_periodic_cleanup, daemon=True).start()
        
    return _task_queue

def _periodic_cleanup() -> None:
    """Periodically clean up completed tasks."""
    while True:
        try:
            time.sleep(3600)  # Sleep for 1 hour
            if _task_queue:
                _task_queue.cleanup_completed_tasks()
        except Exception as e:
            logger.exception(f"Error in periodic cleanup: {e}")

# Convenience functions
def create_task(task_type: str, user_id: str = "anonymous") -> Task:
    """Create a new task."""
    return get_task_queue().create_task(task_type, user_id)

def get_task(task_id: str) -> Optional[Task]:
    """Get a task by ID."""
    return get_task_queue().get_task(task_id)

def list_tasks(user_id: Optional[str] = None, limit: int = 100) -> List[Task]:
    """List tasks, optionally filtered by user ID."""
    return get_task_queue().list_tasks(user_id, limit)

def submit_task(task_id: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Submit a task for execution."""
    get_task_queue().submit(task_id, func, *args, **kwargs)

def cancel_task(task_id: str) -> bool:
    """Cancel a task if it's still pending."""
    return get_task_queue().cancel_task(task_id)

def update_task_progress(task_id: str, progress: int, details: Optional[Dict[str, Any]] = None) -> bool:
    """Update the progress of a task."""
    return get_task_queue().update_progress(task_id, progress, details)