"""
Custom logging handlers for Relia OSS.

This module provides:
- Database logging handler to save logs in SQLite
- Access log middleware for recording API requests
- Structured log formatter
"""
import json
import logging
import time
from datetime import datetime

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from . import database

class DatabaseLogHandler(logging.Handler):
    """Logging handler that saves logs to the database."""
    
    def __init__(self, level=logging.INFO):
        """Initialize the database log handler."""
        super().__init__(level)
        self.setFormatter(logging.Formatter(
            '%(levelname)s [%(name)s] %(message)s'
        ))
    
    def emit(self, record):
        """Save the log record to the database."""
        if not settings.DB_ENABLED:
            return
            
        try:
            # Extract log details
            level = record.levelname
            message = self.format(record)
            
            # Extract extra fields if available
            details = {}
            for key, value in record.__dict__.items():
                if key not in ["name", "msg", "args", "levelname", "levelno", 
                               "pathname", "filename", "module", "exc_info", 
                               "exc_text", "lineno", "funcName", "created", 
                               "asctime", "msecs", "relativeCreated", "thread", 
                               "threadName", "processName", "process"]:
                    details[key] = value
            
            # Get source from record
            source = record.name
            
            # Get user_id if in details
            user_id = details.pop("user_id", None)
            
            # Get database connection
            db = database.get_db()
            
            # Save to app_logs table if it exists
            try:
                # Format timestamp
                timestamp = datetime.utcnow().isoformat()
                
                # Convert details to JSON if not empty
                details_json = json.dumps(details) if details else None
                
                db.execute(
                    """INSERT INTO app_logs (level, message, details, timestamp, source, user_id)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (level, message, details_json, timestamp, source, user_id)
                )
            except Exception:
                # If table doesn't exist or other error, silently continue
                pass
                
        except Exception:
            self.handleError(record)

class AccessLogMiddleware(BaseHTTPMiddleware):
    """Middleware that records API request logs to the database."""
    
    async def dispatch(self, request: Request, call_next):
        """Process the request and log it to the database."""
        # Record start time
        start_time = time.time()
        
        # Get request information
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        # Try to get user ID from headers or session
        user_id = request.headers.get("X-User-ID", "anonymous")
        
        try:
            # Process the request
            response = await call_next(request)
            
            # Skip logging for health and metrics endpoints
            if not path.startswith(("/health", "/metrics")) and settings.DB_ENABLED:
                # Calculate duration
                duration_ms = (time.time() - start_time) * 1000
                
                # Get status code
                status_code = response.status_code
                
                # Record access log
                try:
                    database.record_access_log(
                        method=method,
                        path=path,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        ip_address=client_ip,
                        user_agent=user_agent,
                        user_id=user_id
                    )
                except Exception as e:
                    # Log but continue if there's an error
                    logging.getLogger(__name__).error(f"Failed to record access log: {e}")
            
            return response
            
        except Exception as e:
            # Log exception and re-raise
            logging.getLogger(__name__).error(
                f"Error processing request: {e}",
                exc_info=True,
                extra={"path": path, "method": method, "user_id": user_id}
            )
            raise

def setup_logging():
    """Configure logging for the application."""
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '[%(levelname)s] [%(name)s] %(message)s'
    ))
    root_logger.addHandler(console_handler)
    
    # Database handler (if enabled)
    if settings.DB_ENABLED and settings.MONITORING_ENABLED:
        db_handler = DatabaseLogHandler(level=logging.INFO)
        root_logger.addHandler(db_handler)
    
    # Set specific logger levels
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    # Application loggers
    app_logger = logging.getLogger("backend")
    app_logger.setLevel(logging.INFO)
    
    return root_logger