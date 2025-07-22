"""Common test fixtures for Relia OSS."""
import pytest
from unittest.mock import MagicMock

# Add more comprehensive database mocking
@pytest.fixture(scope="session", autouse=True)
def disable_db_pool_logging():
    """Disable noisy database pool logging during tests."""
    import logging
    logging.getLogger("backend.db_pool").setLevel(logging.ERROR)

@pytest.fixture(scope="function", autouse=True)
def setup_test_database(monkeypatch):
    """Create an in-memory test database for each test."""
    # First, mock the database connection to prevent real DB operations
    mock_pool = MagicMock()
    mock_pool.get_connection.return_value.__enter__.return_value = MagicMock()
    mock_pool.get_cursor.return_value.__enter__.return_value = MagicMock()
    mock_pool.transaction.return_value.__enter__.return_value = MagicMock()
    mock_pool.execute.return_value = MagicMock()
    mock_pool.executemany.return_value = MagicMock()
    mock_pool.fetchone.return_value = {}
    mock_pool.fetchall.return_value = []
    
    # Replace all database functions
    monkeypatch.setattr("backend.db_pool._db_pool", mock_pool)
    monkeypatch.setattr("backend.db_pool.get_pool", lambda: mock_pool)
    monkeypatch.setattr("backend.db_pool.init_pool", lambda **kwargs: mock_pool)
    monkeypatch.setattr("backend.db_pool.get_connection", lambda: mock_pool.get_connection())
    monkeypatch.setattr("backend.db_pool.get_cursor", lambda: mock_pool.get_cursor())
    monkeypatch.setattr("backend.db_pool.transaction", lambda: mock_pool.transaction())
    monkeypatch.setattr("backend.db_pool.execute", lambda *args, **kwargs: mock_pool.execute(*args, **kwargs))
    monkeypatch.setattr("backend.db_pool.executemany", lambda *args, **kwargs: mock_pool.executemany(*args, **kwargs))
    monkeypatch.setattr("backend.db_pool.fetchone", lambda *args, **kwargs: mock_pool.fetchone(*args, **kwargs))
    monkeypatch.setattr("backend.db_pool.fetchall", lambda *args, **kwargs: mock_pool.fetchall(*args, **kwargs))
    
    # Mock the Database class
    mock_db = MagicMock()
    mock_db.connect.return_value = MagicMock()
    mock_db.initialize.return_value = True
    mock_db.execute.return_value = MagicMock()
    mock_db.transaction.return_value.__enter__.return_value = MagicMock()
    monkeypatch.setattr("backend.database.Database", lambda *args, **kwargs: mock_db)
    
    # Mock database initialization
    monkeypatch.setattr("backend.database.initialize_database", lambda **kwargs: True)
    
    # Disable database usage for tests
    monkeypatch.setattr("backend.app.settings.DB_ENABLED", False)
    
    # Mock database functions
    monkeypatch.setattr("backend.database.record_telemetry", lambda *args, **kwargs: 1)
    monkeypatch.setattr("backend.database.record_feedback", lambda *args, **kwargs: 1)
    monkeypatch.setattr("backend.database.record_playbook", lambda *args, **kwargs: "test-id")
    monkeypatch.setattr("backend.database.get_feedback", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.database.get_telemetry", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.database.get_playbook", lambda *args, **kwargs: {"playbook_id": "test-id"})
    monkeypatch.setattr("backend.database.get_playbooks", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.database.get_llm_usage_stats", lambda *args, **kwargs: {"total_tokens": 0, "total_requests": 0, "providers": []})
    
    # Mock cache
    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mock_cache.set.return_value = True
    mock_cache.clear.return_value = True
    mock_cache.stats.return_value = {"hits": 0, "misses": 0, "size": 0}
    monkeypatch.setattr("backend.cache.schema_cache", mock_cache)
    monkeypatch.setattr("backend.cache.llm_cache", mock_cache)
    monkeypatch.setattr("backend.cache.playbook_cache", mock_cache)
    
    yield
    # No teardown needed for mock database