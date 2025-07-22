"""
Database connection pooling for Relia OSS.

This module provides a connection pool for SQL databases.
It supports both SQLite and PostgreSQL.
"""
import atexit
import logging
import os
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

# Configure module logger
logger = logging.getLogger(__name__)

# Try to import SQLAlchemy for real database connection pooling
try:
    from sqlalchemy import create_engine, text
    HAVE_SQLALCHEMY = True
except ImportError:
    logger.warning("SQLAlchemy not installed, using basic connection pool")
    HAVE_SQLALCHEMY = False

# SQLite connection pool logic follows

class ConnectionPool:
    """Generic database connection pool."""
    
    def __init__(
        self,
        connection_string: str,
        min_connections: int = 5,
        max_connections: int = 20,
        timeout: int = 30,
        max_overflow: int = 10,
        recycle_seconds: int = 1800,
        echo: bool = False,
    ):
        """Initialize the connection pool.
        
        Args:
            connection_string: Database connection string
            min_connections: Minimum number of connections to keep open
            max_connections: Maximum number of connections in the pool
            timeout: Timeout in seconds for getting a connection
            max_overflow: Maximum number of connections that can be created beyond the pool size
            recycle_seconds: Number of seconds after which a connection is recycled
            echo: Whether to echo SQL statements
        """
        self.connection_string = connection_string
        self.min_connections = min_connections
        self.max_connections = max_connections
        self.timeout = timeout
        self.max_overflow = max_overflow
        self.recycle_seconds = recycle_seconds
        self.echo = echo
        
        self.is_sqlite = connection_string.startswith("sqlite")
        
        # Thread local storage for connection tracking
        self._thread_local = threading.local()
        
        if HAVE_SQLALCHEMY:
            self._init_sqlalchemy_pool()
        else:
            self._init_basic_pool()
            
        logger.info(f"Initialized connection pool: {self.__class__.__name__}")
        
    def _init_sqlalchemy_pool(self):
        """Initialize SQLAlchemy connection pool."""
        # Check if this is an in-memory SQLite database
        is_memory_db = self.connection_string == "sqlite:///:memory:"
        
        if is_memory_db:
            # For in-memory SQLite, use simplified connection parameters
            # as it requires a different pool implementation
            engine_args = {
                "echo": self.echo,
                "connect_args": {
                    "check_same_thread": False,
                }
            }
            logger.info("Using in-memory SQLite database with singleton pool")
        else:
            # Normal database connection with full connection pool
            engine_args = {
                "pool_size": self.min_connections,
                "max_overflow": self.max_overflow,
                "pool_timeout": self.timeout,
                "pool_recycle": self.recycle_seconds,
                "echo": self.echo,
            }
            
            # For SQLite (file-based), we need to handle some options differently
            if self.is_sqlite and not is_memory_db:
                # Enable foreign keys and WAL mode for SQLite
                engine_args["connect_args"] = {
                    "check_same_thread": False,
                    "timeout": self.timeout,
                }
            
        # Create the engine with the appropriate arguments
        self.engine = create_engine(self.connection_string, **engine_args)
        
    def _init_basic_pool(self):
        """Initialize a basic connection pool for when SQLAlchemy is not available."""
        self._pool = queue.Queue(maxsize=self.max_connections)
        self._connections_in_use = 0
        self._pool_lock = threading.RLock()
        
        # Pre-create minimum connections
        for _ in range(self.min_connections):
            conn = self._create_connection()
            self._pool.put(conn)
    
    def _create_connection(self):
        """Create a new database connection."""
        if self.is_sqlite:
            # For SQLite
            path = self.connection_string.replace("sqlite:///", "")
            conn = sqlite3.connect(
                path,
                timeout=self.timeout,
                isolation_level=None,  # Autocommit mode
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            
            # Enable foreign keys
            conn.execute("PRAGMA foreign_keys = ON")
            
            # Use WAL mode for better concurrency
            conn.execute("PRAGMA journal_mode = WAL")
            
            # Timestamp for connection creation
            conn._created_at = time.time()
            
            return conn
        else:
            # For other databases, this should be handled by SQLAlchemy
            raise NotImplementedError(
                "Basic connection pool only supports SQLite. Install SQLAlchemy for other databases."
            )
    
    def _get_basic_connection(self):
        """Get a connection from the basic pool."""
        with self._pool_lock:
            # Check if we need to create a new connection
            if self._pool.empty() and self._connections_in_use < self.max_connections + self.max_overflow:
                # Create a new connection
                conn = self._create_connection()
                self._connections_in_use += 1
                return conn
                
            # Wait for a connection from the pool
            try:
                conn = self._pool.get(timeout=self.timeout)
                self._connections_in_use += 1
                
                # Check if connection needs to be recycled
                if hasattr(conn, "_created_at") and time.time() - conn._created_at > self.recycle_seconds:
                    # Close old connection and create a new one
                    try:
                        conn.close()
                    except Exception as e:
                        logger.warning(f"Error closing old connection: {e}")
                    
                    conn = self._create_connection()
                    
                return conn
            except queue.Empty:
                raise TimeoutError("Timeout waiting for database connection")
                
    def _return_basic_connection(self, conn):
        """Return a connection to the basic pool."""
        with self._pool_lock:
            self._connections_in_use -= 1
            
            try:
                # Check if connection is still usable
                if self.is_sqlite:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    cursor.close()
                    
                # Put it back in the pool
                self._pool.put(conn, block=False)
            except Exception as e:
                logger.warning(f"Connection returned to pool is not usable: {e}")
                # Create a new connection to replace it
                try:
                    new_conn = self._create_connection()
                    self._pool.put(new_conn, block=False)
                except Exception as e2:
                    logger.error(f"Failed to create replacement connection: {e2}")

    @contextmanager
    def get_connection(self):
        """Get a connection from the pool."""
        connection = None
        
        # Check if there's already a connection in thread local storage
        if hasattr(self._thread_local, "connection"):
            connection = self._thread_local.connection
            # Increment the reference count
            self._thread_local.ref_count += 1
            yield connection
            # Decrement the reference count
            self._thread_local.ref_count -= 1
            # Only release the connection when the reference count is 0
            if self._thread_local.ref_count <= 0:
                self._release_connection()
            return
            
        # Get a new connection
        try:
            if HAVE_SQLALCHEMY:
                connection = self.engine.connect()
                self._thread_local.connection = connection
                self._thread_local.ref_count = 1
                yield connection
                # Connection will be returned to the pool by SQLAlchemy
                # when it's closed in the finally block
            else:
                connection = self._get_basic_connection()
                self._thread_local.connection = connection
                self._thread_local.ref_count = 1
                yield connection
        except Exception as e:
            logger.error(f"Error getting database connection: {e}")
            raise
        finally:
            # Release the connection if we've created a new one
            if hasattr(self._thread_local, "connection") and self._thread_local.ref_count <= 1:
                self._release_connection()
    
    def _release_connection(self):
        """Release the connection associated with the current thread."""
        connection = getattr(self._thread_local, "connection", None)
        if connection:
            try:
                if HAVE_SQLALCHEMY:
                    connection.close()
                else:
                    self._return_basic_connection(connection)
            except Exception as e:
                logger.error(f"Error releasing connection: {e}")
            
            delattr(self._thread_local, "connection")
            delattr(self._thread_local, "ref_count")
    
    @contextmanager
    def get_cursor(self):
        """Get a cursor from a connection in the pool."""
        with self.get_connection() as connection:
            if HAVE_SQLALCHEMY:
                # For SQLAlchemy, we need to create a raw connection cursor
                with connection.begin():
                    if self.is_sqlite:
                        # Get the raw connection for SQLite
                        raw_conn = connection.connection
                        cursor = raw_conn.cursor()
                        yield cursor
                    else:
                        # For other databases, use connection.execute() directly
                        yield connection
            else:
                # For the basic pool, we can create a cursor directly
                cursor = connection.cursor()
                yield cursor
                
    @contextmanager
    def transaction(self):
        """Start a transaction context."""
        with self.get_connection() as connection:
            if HAVE_SQLALCHEMY:
                # Use SQLAlchemy's transaction
                with connection.begin():
                    try:
                        yield connection
                        # Transaction will be committed when the context exits if no exception
                    except Exception:
                        # Transaction will be rolled back on exception
                        raise
            else:
                # For the basic pool, manage transaction manually
                cursor = connection.cursor()
                cursor.execute("BEGIN TRANSACTION")
                try:
                    yield cursor
                    cursor.execute("COMMIT")
                except Exception:
                    cursor.execute("ROLLBACK")
                    raise
    
    def execute(self, query, params=None):
        """Execute a SQL query with parameters."""
        with self.get_cursor() as cursor:
            if HAVE_SQLALCHEMY and not self.is_sqlite:
                # For SQLAlchemy with non-SQLite, use text()
                result = cursor.execute(text(query), params or {})
                return result
            else:
                # For SQLite or basic pool, use cursor directly
                return cursor.execute(query, params or ())
    
    def executemany(self, query, params_list):
        """Execute a SQL query with multiple parameter sets."""
        with self.get_cursor() as cursor:
            if HAVE_SQLALCHEMY and not self.is_sqlite:
                # For SQLAlchemy with non-SQLite, use text() and handle batch execution
                for params in params_list:
                    cursor.execute(text(query), params)
                return cursor
            else:
                # For SQLite or basic pool, use cursor.executemany directly
                return cursor.executemany(query, params_list)
    
    def fetchone(self, query, params=None):
        """Execute a query and fetch a single result."""
        with self.get_cursor() as cursor:
            if HAVE_SQLALCHEMY and not self.is_sqlite:
                result = cursor.execute(text(query), params or {})
                row = result.fetchone()
                if row:
                    # Convert RowMapping to dict for a more consistent return type
                    return dict(row)
                return None
            else:
                cursor.execute(query, params or ())
                row = cursor.fetchone()
                return dict(row) if row else None
    
    def fetchall(self, query, params=None):
        """Execute a query and fetch all results."""
        with self.get_cursor() as cursor:
            if HAVE_SQLALCHEMY and not self.is_sqlite:
                result = cursor.execute(text(query), params or {})
                rows = result.fetchall()
                # Convert to a list of dicts
                return [dict(row) for row in rows]
            else:
                cursor.execute(query, params or ())
                return [dict(row) for row in cursor.fetchall()]
    
    def close_all(self):
        """Close all connections in the pool."""
        if HAVE_SQLALCHEMY:
            # Close the engine which will dispose the pool
            self.engine.dispose()
        else:
            # Close all connections in the basic pool
            with self._pool_lock:
                while not self._pool.empty():
                    try:
                        conn = self._pool.get_nowait()
                        conn.close()
                    except Exception as e:
                        logger.warning(f"Error closing connection: {e}")

# Global connection pool
_db_pool = None
_db_pool_lock = threading.RLock()

def init_pool(
    connection_string: Optional[str] = None,
    min_connections: int = 5,
    max_connections: int = 20,
    timeout: int = 30,
    max_overflow: int = 10,
    recycle_seconds: int = 1800,
    echo: bool = False,
) -> ConnectionPool:
    """Initialize the global connection pool.
    
    Args:
        connection_string: Database connection string
        min_connections: Minimum number of connections to keep open
        max_connections: Maximum number of connections in the pool
        timeout: Timeout in seconds for getting a connection
        max_overflow: Maximum number of connections that can be created beyond the pool size
        recycle_seconds: Number of seconds after which a connection is recycled
        echo: Whether to echo SQL statements
        
    Returns:
        The initialized connection pool
    """
    global _db_pool
    
    # Use environment variable for connection string if not provided
    if connection_string is None:
        connection_string = os.environ.get("RELIA_DB_URL", "sqlite:///relia-data/relia.db")
    
    with _db_pool_lock:
        if _db_pool is None:
            _db_pool = ConnectionPool(
                connection_string=connection_string,
                min_connections=min_connections,
                max_connections=max_connections,
                timeout=timeout,
                max_overflow=max_overflow,
                recycle_seconds=recycle_seconds,
                echo=echo,
            )
    
    return _db_pool

def get_pool() -> ConnectionPool:
    """Get the global connection pool, initializing it if necessary."""
    global _db_pool
    
    with _db_pool_lock:
        if _db_pool is None:
            _db_pool = init_pool()
    
    return _db_pool

@contextmanager
def get_connection():
    """Get a connection from the global pool."""
    pool = get_pool()
    with pool.get_connection() as conn:
        yield conn

@contextmanager
def get_cursor():
    """Get a cursor from a connection in the global pool."""
    pool = get_pool()
    with pool.get_cursor() as cursor:
        yield cursor

@contextmanager
def transaction():
    """Start a transaction context."""
    pool = get_pool()
    with pool.transaction() as cursor:
        yield cursor

def execute(query, params=None):
    """Execute a SQL query with parameters."""
    pool = get_pool()
    return pool.execute(query, params)

def executemany(query, params_list):
    """Execute a SQL query with multiple parameter sets."""
    pool = get_pool()
    return pool.executemany(query, params_list)

def fetchone(query, params=None):
    """Execute a query and fetch a single result."""
    pool = get_pool()
    return pool.fetchone(query, params)

def fetchall(query, params=None):
    """Execute a query and fetch all results."""
    pool = get_pool()
    return pool.fetchall(query, params)

def close_all():
    """Close all connections in the pool."""
    global _db_pool
    
    with _db_pool_lock:
        if _db_pool is not None:
            _db_pool.close_all()
            _db_pool = None

# Clean up connections on exit
atexit.register(close_all)