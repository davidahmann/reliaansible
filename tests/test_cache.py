"""Tests for the caching system."""
import time
from unittest.mock import MagicMock

from backend.cache import Cache, CacheEntry, cached

def test_cache_entry_expiration():
    """Test that cache entries expire correctly."""
    # Create entry with 1 second TTL
    entry = CacheEntry("test_value", ttl_seconds=1)
    
    # Should not be expired immediately
    assert not entry.is_expired()
    
    # Should be expired after 1.1 seconds
    time.sleep(1.1)
    assert entry.is_expired()

def test_cache_get_set():
    """Test basic cache get/set operations."""
    cache = Cache[str]("test", ttl_seconds=30)
    
    # Set and get an item
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    
    # Get a non-existent item
    assert cache.get("key2") is None
    
    # Set an item with custom TTL
    cache.set("key2", "value2", ttl_seconds=0.1)
    assert cache.get("key2") == "value2"
    
    # Wait for key2 to expire
    time.sleep(0.2)
    assert cache.get("key2") is None

def test_cache_delete():
    """Test deleting items from the cache."""
    cache = Cache[str]("test", ttl_seconds=30)
    
    # Set some items
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    
    # Delete an item
    cache.delete("key1")
    assert cache.get("key1") is None
    assert cache.get("key2") == "value2"
    
    # Delete a non-existent item
    cache.delete("key3")  # Should not raise an error

def test_cache_clear():
    """Test clearing the entire cache."""
    cache = Cache[str]("test", ttl_seconds=30)
    
    # Set some items
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    
    # Clear the cache
    cache.clear()
    assert cache.get("key1") is None
    assert cache.get("key2") is None
    assert len(cache) == 0

def test_cache_cleanup():
    """Test that expired entries are cleaned up."""
    # Create cache with 0.1 second TTL and 0.2 second cleanup interval
    cache = Cache[str]("test", ttl_seconds=0.1, cleanup_interval=0.2)
    
    # Set some items
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    assert len(cache) == 2
    
    # Wait for items to expire and cleanup to happen
    time.sleep(0.3)
    
    # Force a cache operation to trigger cleanup
    cache.get("key3")
    
    # Verify that expired items are removed
    assert len(cache) == 0

def test_cached_decorator():
    """Test the cached decorator."""
    cache = Cache[int]("test", ttl_seconds=30)
    
    # Create a mock function that counts calls
    counter = MagicMock()
    
    @cached(cache)
    def expensive_function(x, y):
        counter()
        return x + y
    
    # First call should compute the result
    assert expensive_function(1, 2) == 3
    assert counter.call_count == 1
    
    # Second call with same args should use cache
    assert expensive_function(1, 2) == 3
    assert counter.call_count == 1
    
    # Call with different args should compute again
    assert expensive_function(2, 3) == 5
    assert counter.call_count == 2
    
    # Clear cache and call again
    cache.clear()
    assert expensive_function(1, 2) == 3
    assert counter.call_count == 3

def test_cached_decorator_with_key_fn():
    """Test the cached decorator with a custom key function."""
    cache = Cache[str]("test", ttl_seconds=30)
    
    # Define a custom key function
    def key_fn(prefix, value):
        return f"{prefix}:{value}"
    
    # Create a mock function that counts calls
    counter = MagicMock()
    
    @cached(cache, key_fn=key_fn)
    def get_greeting(prefix, name):
        counter()
        return f"{prefix} {name}"
    
    # First call should compute the result
    assert get_greeting("Hello", "Alice") == "Hello Alice"
    assert counter.call_count == 1
    
    # Second call with same args should use cache
    assert get_greeting("Hello", "Alice") == "Hello Alice"
    assert counter.call_count == 1
    
    # Call with different args should compute again
    assert get_greeting("Hi", "Bob") == "Hi Bob"
    assert counter.call_count == 2