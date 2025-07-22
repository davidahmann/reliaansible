"""
Database module for Relia OSS.

Provides:
- Database connection management with connection pooling
- Schema initialization and migrations
- Data access functions for telemetry and feedback
"""
import sqlite3
import logging
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

from .config import settings
from .db_pool import init_pool, get_pool, transaction, fetchall

# Configure logger
logger = logging.getLogger(__name__)

# SQL statements for table creation
SCHEMA_SQL = """
-- Feedback table for storing user ratings and comments
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playbook_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous'
);

-- Telemetry table for storing usage data
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    event_data TEXT NOT NULL,  -- JSON string
    created_at TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous',
    session_id TEXT
);

-- Playbook metadata table
CREATE TABLE IF NOT EXISTS playbooks (
    playbook_id TEXT PRIMARY KEY,
    module TEXT NOT NULL,
    prompt TEXT NOT NULL,
    yaml_content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    user_id TEXT DEFAULT 'anonymous',
    status TEXT DEFAULT 'created'
);

-- LLM Usage metrics
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    duration_ms INTEGER,
    created_at TEXT NOT NULL,
    request_id TEXT,
    user_id TEXT DEFAULT 'anonymous'
);

-- Application logs
CREATE TABLE IF NOT EXISTS app_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    timestamp TEXT NOT NULL,
    source TEXT,
    user_id TEXT
);

-- Access logs
CREATE TABLE IF NOT EXISTS access_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    user_id TEXT,
    timestamp TEXT NOT NULL,
    duration_ms REAL
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_feedback_playbook_id ON feedback(playbook_id);
CREATE INDEX IF NOT EXISTS idx_telemetry_event_type ON telemetry(event_type);
CREATE INDEX IF NOT EXISTS idx_telemetry_created_at ON telemetry(created_at);
CREATE INDEX IF NOT EXISTS idx_playbooks_module ON playbooks(module);
CREATE INDEX IF NOT EXISTS idx_playbooks_created_at ON playbooks(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_provider ON llm_usage(provider);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at ON llm_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_app_logs_timestamp ON app_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_app_logs_level ON app_logs(level);
CREATE INDEX IF NOT EXISTS idx_access_logs_timestamp ON access_logs(timestamp);
"""

class Database:
    """Database connection manager for SQLite."""
    
    def __init__(self, db_path: Optional[Path] = None, in_memory: bool = False):
        """Initialize the database manager.
        
        Args:
            db_path: Path to the SQLite database file. If None, uses the default
                    path from settings.
            in_memory: If True, creates an in-memory database for testing
        """
        self.in_memory = in_memory
        if in_memory:
            self.db_path = ":memory:"
            logger.info("Using in-memory database for testing")
        else:
            self.db_path = db_path or settings.DATA_DIR / "relia.db"
            self.ensure_dir()
        self._conn = None
        
    def ensure_dir(self):
        """Ensure the directory for the database exists."""
        if not self.in_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
    def connect(self):
        """Get a database connection, creating one if needed."""
        if self._conn is None:
            try:
                conn_string = ":memory:" if self.in_memory else str(self.db_path)
                self._conn = sqlite3.connect(
                    conn_string,
                    detect_types=sqlite3.PARSE_DECLTYPES,
                    isolation_level=None,  # autocommit mode
                    check_same_thread=False,  # allow multi-thread access
                )
                self._conn.row_factory = sqlite3.Row
                logger.info(f"Connected to database: {conn_string}")
            except sqlite3.Error as e:
                logger.error(f"Database connection error: {e}")
                raise
                
        return self._conn
        
    def close(self):
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.debug("Database connection closed")
            
    def initialize(self):
        """Initialize the database schema if needed."""
        conn = self.connect()
        try:
            conn.executescript(SCHEMA_SQL)
            logger.info("Database schema initialized")
        except sqlite3.Error as e:
            logger.error(f"Schema initialization error: {e}")
            raise
            
    def execute(self, sql: str, params=None):
        """Execute a SQL statement with parameters."""
        params = params or ()
        conn = self.connect()
        try:
            return conn.execute(sql, params)
        except sqlite3.Error as e:
            logger.error(f"SQL execution error: {e}")
            logger.error(f"SQL: {sql}, params: {params}")
            raise
            
    def executemany(self, sql: str, params_list):
        """Execute a SQL statement with multiple parameter sets."""
        conn = self.connect()
        try:
            return conn.executemany(sql, params_list)
        except sqlite3.Error as e:
            logger.error(f"SQL execution error: {e}")
            logger.error(f"SQL: {sql}")
            raise
    
    def transaction(self):
        """Start a transaction context."""
        conn = self.connect()
        return conn.cursor()

# Initialize database with connection pool
def initialize_database(force_init: bool = False, in_memory: bool = False):
    """Initialize the database schema and connection pool.
    
    Args:
        force_init: If True, forcibly reinitialize the database schema
        in_memory: If True, use an in-memory database for testing
        
    Returns:
        True if initialization was successful
    """
    # Determine database URL
    if in_memory:
        # Use in-memory database for testing
        db_url = "sqlite:///:memory:"
        logger.info("Using in-memory database for testing")
    else:
        # Create database directory if it doesn't exist
        data_dir = settings.DATA_DIR
        data_dir.mkdir(parents=True, exist_ok=True)
        
        # Use file-based database
        db_url = os.environ.get(
            "RELIA_DB_URL", 
            f"sqlite:///{data_dir}/relia.db"
        )
    
    # Initialize connection pool
    init_pool(
        connection_string=db_url,
        min_connections=5,
        max_connections=20,
        timeout=30,
        max_overflow=10,
        recycle_seconds=1800,  # 30 minutes
        echo=settings.ENV == "dev"  # Enable query logging in dev
    )
    
    try:
        # Create schema if needed
        with transaction() as conn:
            # executescript is a SQLite-specific method that may not be available in all DB API connections
            # Try different methods to execute the SQL script
            try:
                # Try to use executescript if available (SQLite)
                if hasattr(conn, 'executescript'):
                    conn.executescript(SCHEMA_SQL)
                # Otherwise try executing as a whole script
                elif hasattr(conn, 'execute'):
                    conn.execute(SCHEMA_SQL)
                # If we have a cursor object, not a connection
                elif hasattr(conn, 'cursor'):
                    # Use the cursor to execute the script
                    cursor = conn.cursor()
                    cursor.executescript(SCHEMA_SQL) if hasattr(cursor, 'executescript') else cursor.execute(SCHEMA_SQL)
                else:
                    # Fall back to splitting and executing statement by statement
                    for statement in SCHEMA_SQL.split(';'):
                        # Skip empty statements
                        if statement.strip():
                            conn.execute(statement)
            except Exception as script_error:
                logger.error(f"Error executing schema script: {script_error}")
                # Try statement by statement as a fallback
                for statement in SCHEMA_SQL.split(';'):
                    # Skip empty statements
                    if statement.strip():
                        conn.execute(statement)
            
        logger.info(f"Database initialized successfully: {db_url}")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return False

def get_db(force_init: bool = False):
    """Get the database connection pool.
    
    This compatibility function maintains the old API but uses
    the new connection pool.
    
    Args:
        force_init: If True, reinitialize the database schema
        
    Returns:
        The database connection pool
    """
    if force_init:
        initialize_database(force_init=True)
        
    return get_pool()

@contextmanager
def db_transaction():
    """Context manager for database transactions.
    
    Usage:
        with db_transaction() as cursor:
            cursor.execute("INSERT INTO...")
            cursor.execute("UPDATE...")
    """
    with transaction() as cursor:
        yield cursor

# ----------------------------------------------------------------
# Feedback functions
# ----------------------------------------------------------------
def record_feedback(playbook_id: str, rating: int, comment: Optional[str] = None, 
                    user_id: str = "anonymous") -> int:
    """Record feedback for a playbook.
    
    Args:
        playbook_id: ID of the playbook
        rating: Rating from 1-5
        comment: Optional comment
        user_id: User ID (defaults to "anonymous")
        
    Returns:
        ID of the new feedback record
    """
    created_at = datetime.utcnow().isoformat()
    
    with transaction() as cursor:
        cursor.execute(
            """INSERT INTO feedback (playbook_id, rating, comment, created_at, user_id)
               VALUES (?, ?, ?, ?, ?)""",
            (playbook_id, rating, comment, created_at, user_id)
        )
        # Get last insert ID - different approaches for different databases
        if isinstance(cursor, sqlite3.Cursor):
            lastrowid = cursor.lastrowid
        else:
            # For other databases via SQLAlchemy
            result = cursor.execute("SELECT last_insert_rowid()")
            lastrowid = result.scalar() if hasattr(result, "scalar") else cursor.lastrowid
    
    logger.info(f"Recorded feedback for playbook {playbook_id}: rating={rating}")
    return lastrowid

def get_feedback(playbook_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Get feedback records, optionally filtered by playbook.
    
    Args:
        playbook_id: Optional playbook ID to filter by
        limit: Maximum number of records to return
        
    Returns:
        List of feedback records as dictionaries
    """
    if playbook_id:
        return fetchall(
            """SELECT * FROM feedback WHERE playbook_id = ? ORDER BY created_at DESC LIMIT ?""",
            (playbook_id, limit)
        )
    else:
        return fetchall(
            """SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        )

# ----------------------------------------------------------------
# Telemetry functions
# ----------------------------------------------------------------
def record_telemetry(event_type: str, event_data: Dict[str, Any], 
                     user_id: str = "anonymous", session_id: Optional[str] = None) -> int:
    """Record a telemetry event.
    
    Args:
        event_type: Type of event (e.g., "generate", "lint", "test")
        event_data: Dictionary of event data
        user_id: User ID (defaults to "anonymous")
        session_id: Optional session ID
        
    Returns:
        ID of the new telemetry record
    """
    db = get_db()
    created_at = datetime.utcnow().isoformat()
    event_json = json.dumps(event_data)
    
    cursor = db.execute(
        """INSERT INTO telemetry (event_type, event_data, created_at, user_id, session_id)
           VALUES (?, ?, ?, ?, ?)""",
        (event_type, event_json, created_at, user_id, session_id)
    )
    
    logger.debug(f"Recorded telemetry event: {event_type}")
    return cursor.lastrowid

def get_telemetry(event_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Get telemetry records, optionally filtered by event type.
    
    Args:
        event_type: Optional event type to filter by
        limit: Maximum number of records to return
        
    Returns:
        List of telemetry records as dictionaries, with event_data parsed from JSON
    """
    db = get_db()
    
    if event_type:
        cursor = db.execute(
            """SELECT * FROM telemetry WHERE event_type = ? ORDER BY created_at DESC LIMIT ?""",
            (event_type, limit)
        )
    else:
        cursor = db.execute(
            """SELECT * FROM telemetry ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        )
    
    result = []
    for row in cursor.fetchall():
        row_dict = dict(row)
        try:
            row_dict["event_data"] = json.loads(row_dict["event_data"])
        except json.JSONDecodeError:
            pass  # Keep as string if invalid JSON
        result.append(row_dict)
        
    return result

# ----------------------------------------------------------------
# Playbook functions
# ----------------------------------------------------------------
def record_playbook(playbook_id: str, module: str, prompt: str, yaml_content: str,
                    user_id: str = "anonymous") -> str:
    """Record a generated playbook.
    
    Args:
        playbook_id: ID of the playbook
        module: Ansible module used
        prompt: User prompt
        yaml_content: Generated YAML content
        user_id: User ID (defaults to "anonymous")
        
    Returns:
        Playbook ID
    """
    db = get_db()
    created_at = datetime.utcnow().isoformat()
    
    db.execute(
        """INSERT INTO playbooks (playbook_id, module, prompt, yaml_content, created_at, user_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (playbook_id, module, prompt, yaml_content, created_at, user_id)
    )
    
    logger.info(f"Recorded playbook {playbook_id} for module {module}")
    return playbook_id

def update_playbook_status(playbook_id: str, status: str) -> bool:
    """Update the status of a playbook.
    
    Args:
        playbook_id: ID of the playbook
        status: New status (e.g., "created", "linted", "tested")
        
    Returns:
        True if the playbook was updated, False if not found
    """
    db = get_db()
    
    cursor = db.execute(
        """UPDATE playbooks SET status = ? WHERE playbook_id = ?""",
        (status, playbook_id)
    )
    
    if cursor.rowcount > 0:
        logger.debug(f"Updated playbook {playbook_id} status to {status}")
        return True
    else:
        logger.warning(f"Playbook {playbook_id} not found for status update")
        return False

def get_playbook(playbook_id: str) -> Optional[Dict[str, Any]]:
    """Get a playbook by ID.
    
    Args:
        playbook_id: ID of the playbook
        
    Returns:
        Playbook record as a dictionary, or None if not found
    """
    db = get_db()
    
    cursor = db.execute(
        """SELECT * FROM playbooks WHERE playbook_id = ?""",
        (playbook_id,)
    )
    
    row = cursor.fetchone()
    return dict(row) if row else None

def get_playbooks(module: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Get playbook records, optionally filtered by module.
    
    Args:
        module: Optional module to filter by
        limit: Maximum number of records to return
        
    Returns:
        List of playbook records as dictionaries
    """
    db = get_db()
    
    if module:
        cursor = db.execute(
            """SELECT * FROM playbooks WHERE module = ? ORDER BY created_at DESC LIMIT ?""",
            (module, limit)
        )
    else:
        cursor = db.execute(
            """SELECT * FROM playbooks ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        )
    
    return [dict(row) for row in cursor.fetchall()]

# ----------------------------------------------------------------
# Logging functions
# ----------------------------------------------------------------
def record_access_log(
    method: str, path: str, status_code: int, duration_ms: float,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None,
    user_id: Optional[str] = None
) -> int:
    """Record an HTTP access log entry.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: Request path
        status_code: HTTP status code
        duration_ms: Request duration in milliseconds
        ip_address: Optional client IP address
        user_agent: Optional user agent string
        user_id: Optional user ID
        
    Returns:
        ID of the new access log record, or 0 if failed
    """
    try:
        db = get_db()
        timestamp = datetime.utcnow().isoformat()
        
        # Check if access_logs table exists
        cursor = db.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' AND name='access_logs'"""
        )
        
        # Create table if it doesn't exist
        if not cursor.fetchone():
            db.execute("""
                CREATE TABLE access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    user_id TEXT,
                    timestamp TEXT NOT NULL,
                    duration_ms REAL
                )
            """)
            
            # Create index for fast querying
            db.execute("""
                CREATE INDEX idx_access_logs_timestamp ON access_logs(timestamp)
            """)
        
        # Insert the log entry
        cursor = db.execute(
            """INSERT INTO access_logs (
                method, path, status_code, ip_address, user_agent, 
                user_id, timestamp, duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (method, path, status_code, ip_address, user_agent, 
             user_id, timestamp, duration_ms)
        )
        
        return cursor.lastrowid
    except Exception as e:
        logger.error(f"Failed to record access log: {e}")
        return 0

def get_access_logs(
    limit: int = 100,
    path_prefix: Optional[str] = None,
    status_code: Optional[int] = None,
    user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get access logs with optional filtering.
    
    Args:
        limit: Maximum number of records to return
        path_prefix: Optional path prefix to filter by
        status_code: Optional status code to filter by
        user_id: Optional user ID to filter by
        
    Returns:
        List of access log records as dictionaries
    """
    try:
        db = get_db()
        
        # Check if access_logs table exists
        cursor = db.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' AND name='access_logs'"""
        )
        
        if not cursor.fetchone():
            return []
        
        # Build query and parameters
        query = "SELECT * FROM access_logs"
        params = []
        
        # Add filters
        filters = []
        if path_prefix:
            filters.append("path LIKE ?")
            params.append(f"{path_prefix}%")
        if status_code:
            filters.append("status_code = ?")
            params.append(status_code)
        if user_id:
            filters.append("user_id = ?")
            params.append(user_id)
        
        if filters:
            query += " WHERE " + " AND ".join(filters)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor = db.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Failed to get access logs: {e}")
        return []

def record_log(
    level: str, message: str, details: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None, user_id: Optional[str] = None
) -> int:
    """Record an application log entry.
    
    Args:
        level: Log level (INFO, WARNING, ERROR, etc.)
        message: Log message
        details: Optional details dictionary
        source: Optional log source (module name)
        user_id: Optional user ID
        
    Returns:
        ID of the new log record, or 0 if failed
    """
    try:
        db = get_db()
        timestamp = datetime.utcnow().isoformat()
        
        # Convert details to JSON if not None
        details_json = json.dumps(details) if details else None
        
        # Check if app_logs table exists
        cursor = db.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' AND name='app_logs'"""
        )
        
        # Create table if it doesn't exist
        if not cursor.fetchone():
            db.execute("""
                CREATE TABLE app_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    timestamp TEXT NOT NULL,
                    source TEXT,
                    user_id TEXT
                )
            """)
            
            # Create indexes for fast querying
            db.execute("""
                CREATE INDEX idx_app_logs_timestamp ON app_logs(timestamp)
            """)
            db.execute("""
                CREATE INDEX idx_app_logs_level ON app_logs(level)
            """)
        
        # Insert the log entry
        cursor = db.execute(
            """INSERT INTO app_logs (level, message, details, timestamp, source, user_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (level, message, details_json, timestamp, source, user_id)
        )
        
        return cursor.lastrowid
    except Exception as e:
        # Use print since we can't log a log failure with the logger
        print(f"Failed to record log: {e}")
        return 0

def get_logs(
    limit: int = 100, 
    level: Optional[str] = None, 
    source: Optional[str] = None,
    user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get application logs with optional filtering.
    
    Args:
        limit: Maximum number of records to return
        level: Optional log level to filter by
        source: Optional source to filter by
        user_id: Optional user ID to filter by
        
    Returns:
        List of log records as dictionaries
    """
    try:
        db = get_db()
        
        # Check if app_logs table exists
        cursor = db.execute(
            """SELECT name FROM sqlite_master 
               WHERE type='table' AND name='app_logs'"""
        )
        
        if not cursor.fetchone():
            return []
        
        # Build query and parameters
        query = "SELECT * FROM app_logs"
        params = []
        
        # Add filters
        filters = []
        if level:
            filters.append("level = ?")
            params.append(level)
        if source:
            filters.append("source = ?")
            params.append(source)
        if user_id:
            filters.append("user_id = ?")
            params.append(user_id)
        
        if filters:
            query += " WHERE " + " AND ".join(filters)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor = db.execute(query, params)
        
        results = []
        for row in cursor.fetchall():
            item = dict(row)
            # Parse JSON details
            if item["details"]:
                try:
                    item["details"] = json.loads(item["details"])
                except json.JSONDecodeError:
                    pass  # Keep as string if invalid JSON
            results.append(item)
        
        return results
    except Exception as e:
        logger.error(f"Failed to get logs: {e}")
        return []

# ----------------------------------------------------------------
# LLM Usage functions
# ----------------------------------------------------------------
def record_llm_usage(provider: str, model: str, prompt_tokens: int, completion_tokens: int,
                    duration_ms: int, user_id: str = "anonymous", 
                    request_id: Optional[str] = None) -> int:
    """Record LLM usage metrics.
    
    Args:
        provider: LLM provider (e.g., "openai", "bedrock")
        model: Model name
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        duration_ms: Duration in milliseconds
        user_id: User ID (defaults to "anonymous")
        request_id: Optional request ID
        
    Returns:
        ID of the new usage record
    """
    db = get_db()
    created_at = datetime.utcnow().isoformat()
    total_tokens = prompt_tokens + completion_tokens
    
    cursor = db.execute(
        """INSERT INTO llm_usage 
           (provider, model, prompt_tokens, completion_tokens, total_tokens, 
            duration_ms, created_at, request_id, user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (provider, model, prompt_tokens, completion_tokens, total_tokens,
         duration_ms, created_at, request_id, user_id)
    )
    
    logger.debug(f"Recorded LLM usage: {provider}/{model}, {total_tokens} tokens")
    return cursor.lastrowid

def get_llm_usage_stats(provider: Optional[str] = None, 
                        start_date: Optional[str] = None,
                        end_date: Optional[str] = None) -> Dict[str, Any]:
    """Get aggregated LLM usage statistics.
    
    Args:
        provider: Optional provider to filter by
        start_date: Optional start date (ISO format)
        end_date: Optional end date (ISO format)
        
    Returns:
        Dictionary with usage statistics
    """
    db = get_db()
    
    # Build query and parameters
    query = """
        SELECT 
            provider,
            model,
            COUNT(*) as request_count,
            SUM(prompt_tokens) as total_prompt_tokens,
            SUM(completion_tokens) as total_completion_tokens,
            SUM(total_tokens) as total_tokens,
            AVG(duration_ms) as avg_duration_ms
        FROM llm_usage
        WHERE 1=1
    """
    params = []
    
    if provider:
        query += " AND provider = ?"
        params.append(provider)
        
    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date)
        
    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date)
        
    query += " GROUP BY provider, model"
    
    cursor = db.execute(query, params)
    
    # Convert to a more structured result
    results = [dict(row) for row in cursor.fetchall()]
    
    # Calculate totals across all models
    total_requests = sum(r["request_count"] for r in results)
    total_tokens = sum(r["total_tokens"] for r in results)
    
    return {
        "providers": results,
        "total_requests": total_requests,
        "total_tokens": total_tokens
    }