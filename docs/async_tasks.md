# Asynchronous Task Processing in Relia

This document explains the asynchronous task processing system implemented in Relia.

## Overview

Relia's task system enables the execution of long-running operations in the background, improving overall application responsiveness. Key features include:

1. **Task Queue** - Manages concurrent execution of tasks
2. **Task Status Tracking** - Provides real-time status updates
3. **Error Handling** - Gracefully handles and reports task failures
4. **Progress Reporting** - Allows tasks to report progress
5. **Cancellation** - Supports canceling pending tasks
6. **Cleanup** - Automatically removes old completed tasks

## Architecture

The asynchronous task system consists of several key components:

### Task Queue

A thread-safe queue that manages the lifecycle of tasks, including:

- Creating tasks
- Submitting tasks for execution
- Tracking task status
- Providing task results
- Cleaning up completed tasks

### Tasks

Each task represents a unit of work with the following attributes:

- Unique ID
- Task type
- Status (pending, running, completed, failed, canceled)
- Created/started/completed timestamps
- Progress indicator
- Result or error information
- User ID association

### Executor

Tasks are executed in a thread pool to enable concurrent processing. The default number of worker threads is configurable through the `TASK_MAX_WORKERS` setting.

## API Endpoints

The task system exposes these API endpoints:

### Task Management

- `GET /tasks` - List tasks for the current user
- `GET /tasks/{task_id}` - Get task status
- `GET /tasks/{task_id}/result` - Get task result
- `POST /tasks/{task_id}/cancel` - Cancel a pending task

### Asynchronous Operations

- `POST /async/lint` - Lint a playbook asynchronously
- `POST /async/test` - Test a playbook asynchronously

## Using Asynchronous Operations

Instead of using the synchronous `/lint` and `/test` endpoints, which can block for a long time, you can use the asynchronous variants:

1. Submit an asynchronous operation:
   ```http
   POST /async/lint
   {
     "playbook_id": "123e4567-e89b-12d3-a456-426614174000"
   }
   ```

2. Get a response with the task ID:
   ```json
   {
     "task_id": "987e6543-a21c-34d5-b678-912345678901",
     "playbook_id": "123e4567-e89b-12d3-a456-426614174000",
     "status": "pending"
   }
   ```

3. Check task status periodically:
   ```http
   GET /tasks/987e6543-a21c-34d5-b678-912345678901
   ```

4. When the task is complete, get the result:
   ```http
   GET /tasks/987e6543-a21c-34d5-b678-912345678901/result
   ```

## Task Lifecycle

Tasks go through the following states:

1. **PENDING** - Task has been created but not yet started
2. **RUNNING** - Task is currently being executed
3. **COMPLETED** - Task has completed successfully
4. **FAILED** - Task has failed with an error
5. **CANCELED** - Task was canceled before execution

## Configuration

Task-related settings can be configured through environment variables:

- `RELIA_TASK_MAX_WORKERS` - Maximum number of concurrent task workers (default: 4)
- `RELIA_TASK_CLEANUP_HOURS` - Age in hours after which completed tasks are cleaned up (default: 24)

## Implementation Details

### Thread Safety

The task queue uses a reentrant lock to ensure thread safety when accessing shared data structures.

### Telemetry

Task events are recorded in the telemetry system:

- `task_created` - When a task is created
- `task_started` - When a task starts executing
- `task_completed` - When a task completes successfully
- `task_failed` - When a task fails with an error
- `task_canceled` - When a task is canceled

### Progress Reporting

Long-running tasks can report their progress by updating the task's progress field and providing additional details:

```python
update_task_progress(task_id, 50, {"step": "validating", "file": "playbook.yml"})
```

### Cleanup

A background thread runs periodically to clean up old completed tasks, preventing memory leaks in long-running applications.

## Example: Implementing an Asynchronous Task

Here's how to implement a new asynchronous task:

```python
from backend import tasks

def process_data_async(data_id: str, user_id: str) -> str:
    # Create a task
    task = tasks.create_task("process_data", user_id)
    
    # Store relevant information in the task details
    task.details["data_id"] = data_id
    
    # Submit the task for execution
    tasks.submit_task(
        task.task_id,
        process_data,  # Function to execute
        data_id,       # Arguments to pass
        user_id
    )
    
    return task.task_id

def process_data(data_id: str, user_id: str) -> Dict[str, Any]:
    # This function will be executed in a worker thread
    result = {}
    
    # ... perform long-running operation ...
    
    # Optionally update progress
    tasks.update_task_progress(task_id, 50, {"step": "processing"})
    
    # ... continue processing ...
    
    return result
```

## Best Practices

1. **Use for Long Operations** - Only use the task system for operations that take more than a few seconds
2. **Report Progress** - Update task progress regularly for better user experience
3. **Handle Errors** - Catch and handle exceptions properly to provide meaningful error messages
4. **Clean Resources** - Ensure resources are properly cleaned up, even if the task fails
5. **Limit Concurrency** - Be mindful of resource usage when configuring the number of worker threads