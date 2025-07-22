"""Tests for the asynchronous task processing system."""
import time
from unittest.mock import MagicMock, patch

from backend.tasks import (
    TaskStatus, Task, TaskQueue, create_task, get_task, 
    list_tasks, cancel_task, update_task_progress
)

def test_task_create():
    """Test creating a task."""
    task = Task("test-id", "test", "test-user")
    
    assert task.task_id == "test-id"
    assert task.task_type == "test"
    assert task.user_id == "test-user"
    assert task.status == TaskStatus.PENDING
    assert task.result is None
    assert task.error is None
    assert task.progress == 0
    assert isinstance(task.created_at, str)
    assert task.started_at is None
    assert task.completed_at is None

def test_task_to_dict():
    """Test converting a task to a dictionary."""
    task = Task("test-id", "test", "test-user")
    task_dict = task.to_dict()
    
    assert task_dict["task_id"] == "test-id"
    assert task_dict["task_type"] == "test"
    assert task_dict["user_id"] == "test-user"
    assert task_dict["status"] == TaskStatus.PENDING
    assert task_dict["has_result"] is False
    assert task_dict["has_error"] is False
    assert task_dict["progress"] == 0
    assert "created_at" in task_dict
    assert "details" in task_dict

def test_task_queue_create_task():
    """Test creating a task via the task queue."""
    queue = TaskQueue()
    task = queue.create_task("test", "test-user")
    
    assert task.task_id in queue.tasks
    assert queue.tasks[task.task_id] is task
    assert task.task_type == "test"
    assert task.user_id == "test-user"
    assert task.status == TaskStatus.PENDING

def test_task_queue_get_task():
    """Test getting a task from the queue."""
    queue = TaskQueue()
    task = queue.create_task("test", "test-user")
    
    retrieved = queue.get_task(task.task_id)
    assert retrieved is task
    
    # Non-existent task
    assert queue.get_task("non-existent") is None

def test_task_queue_list_tasks():
    """Test listing tasks."""
    queue = TaskQueue()
    queue.create_task("test1", "user1")
    queue.create_task("test2", "user1")
    queue.create_task("test3", "user2")
    
    # All tasks
    tasks = queue.list_tasks()
    assert len(tasks) == 3
    
    # Filter by user
    user1_tasks = queue.list_tasks(user_id="user1")
    assert len(user1_tasks) == 2
    assert all(t.user_id == "user1" for t in user1_tasks)
    
    user2_tasks = queue.list_tasks(user_id="user2")
    assert len(user2_tasks) == 1
    assert user2_tasks[0].user_id == "user2"
    
    # Limit
    limited_tasks = queue.list_tasks(limit=2)
    assert len(limited_tasks) == 2

def test_task_execution():
    """Test executing a task."""
    queue = TaskQueue()
    
    # Create a mock function
    mock_func = MagicMock(return_value="test-result")
    
    # Create and submit a task
    task = queue.create_task("test", "test-user")
    queue.submit(task.task_id, mock_func, "arg1", kwarg1="kwarg1")
    
    # Wait for the task to complete
    for _ in range(10):  # Wait up to 1 second
        if task.status != TaskStatus.RUNNING:
            break
        time.sleep(0.1)
    
    # Check that the task completed
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "test-result"
    assert task.error is None
    assert task.progress == 100
    assert task.started_at is not None
    assert task.completed_at is not None
    
    # Check that the function was called with the correct arguments
    mock_func.assert_called_once_with("arg1", kwarg1="kwarg1")

def test_task_execution_error():
    """Test executing a task that raises an error."""
    queue = TaskQueue()
    
    # Create a mock function that raises an exception
    mock_func = MagicMock(side_effect=ValueError("test-error"))
    
    # Create and submit a task
    task = queue.create_task("test", "test-user")
    queue.submit(task.task_id, mock_func)
    
    # Wait for the task to complete
    for _ in range(10):  # Wait up to 1 second
        if task.status != TaskStatus.RUNNING:
            break
        time.sleep(0.1)
    
    # Check that the task failed
    assert task.status == TaskStatus.FAILED
    assert task.result is None
    assert task.error == "test-error"
    assert task.started_at is not None
    assert task.completed_at is not None

def test_task_cancel():
    """Test canceling a task."""
    queue = TaskQueue()
    
    # Create a task
    task = queue.create_task("test", "test-user")
    
    # Cancel the task
    assert queue.cancel_task(task.task_id) is True
    assert task.status == TaskStatus.CANCELED
    assert task.completed_at is not None
    
    # Try to cancel a non-existent task
    assert queue.cancel_task("non-existent") is False
    
    # Try to cancel a running task
    task = queue.create_task("test", "test-user")
    task.status = TaskStatus.RUNNING
    assert queue.cancel_task(task.task_id) is False

def test_task_update_progress():
    """Test updating task progress."""
    queue = TaskQueue()
    
    # Create a task
    task = queue.create_task("test", "test-user")
    task.status = TaskStatus.RUNNING
    
    # Update progress
    assert queue.update_progress(task.task_id, 50) is True
    assert task.progress == 50
    
    # Update progress with details
    assert queue.update_progress(task.task_id, 75, {"status": "processing"}) is True
    assert task.progress == 75
    assert task.details["status"] == "processing"
    
    # Try to update a non-existent task
    assert queue.update_progress("non-existent", 100) is False
    
    # Try to update a completed task
    task.status = TaskStatus.COMPLETED
    assert queue.update_progress(task.task_id, 100) is False

def test_task_cleanup():
    """Test cleaning up completed tasks."""
    queue = TaskQueue()
    
    # Create some tasks
    task1 = queue.create_task("test1", "user1")
    task2 = queue.create_task("test2", "user1")
    task3 = queue.create_task("test3", "user2")
    
    # Mark tasks as completed or failed
    task1.status = TaskStatus.COMPLETED
    task1.completed_at = "2000-01-01T00:00:00"  # Old task
    
    task2.status = TaskStatus.FAILED
    task2.completed_at = "2000-01-01T00:00:00"  # Old task
    
    # Keep task3 as pending
    
    # Clean up old tasks
    count = queue.cleanup_completed_tasks()
    
    # Check that only the old completed/failed tasks were removed
    assert count == 2
    assert task1.task_id not in queue.tasks
    assert task2.task_id not in queue.tasks
    assert task3.task_id in queue.tasks

# Test the convenience functions
def test_convenience_functions():
    """Test the convenience functions that use the global task queue."""
    # Create mock task queue
    mock_queue = MagicMock()
    mock_queue.create_task.return_value = "task1"
    mock_queue.get_task.return_value = "task2"
    mock_queue.list_tasks.return_value = ["task3"]
    mock_queue.cancel_task.return_value = True
    mock_queue.update_progress.return_value = True
    
    # Patch the global task queue
    with patch("backend.tasks.get_task_queue", return_value=mock_queue):
        # Test create_task
        assert create_task("test", "user") == "task1"
        mock_queue.create_task.assert_called_once_with("test", "user")
        
        # Test get_task
        assert get_task("task-id") == "task2"
        mock_queue.get_task.assert_called_once_with("task-id")
        
        # Test list_tasks
        assert list_tasks("user", 10) == ["task3"]
        mock_queue.list_tasks.assert_called_once_with("user", 10)
        
        # Test cancel_task
        assert cancel_task("task-id") is True
        mock_queue.cancel_task.assert_called_once_with("task-id")
        
        # Test update_task_progress
        assert update_task_progress("task-id", 50, {"status": "test"}) is True
        mock_queue.update_progress.assert_called_once_with("task-id", 50, {"status": "test"})