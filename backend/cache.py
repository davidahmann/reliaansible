"""
Caching utilities for the Relia backend.

Provides:
- Schema caching with TTL
- LLM response caching
- In-memory cache with cleanup
"""
import time
import logging
import threading
from typing import Any, Dict, Optional, Tuple, TypeVar, Generic, Callable
from functools import wraps

# Configure logger
logger = logging.getLogger(__name__)

T = TypeVar('T')

class CacheEntry(Generic[T]):
    """A cache entry with expiration time."""
    
    def __init__(self, value: T, ttl_seconds: int = 3600):
        """Initialize a cache entry.
        
        Args:
            value: The value to cache
            ttl_seconds: Time to live in seconds (default: 1 hour)
        """
        self.value = value
        self.expiry = time.time() + ttl_seconds
        
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return time.time() > self.expiry

class Cache(Generic[T]):
    """Thread-safe cache with automatic cleanup."""
    
    def __init__(self, name: str, ttl_seconds: int = 3600, cleanup_interval: int = 300):
        """Initialize the cache.
        
        Args:
            name: Cache name for logging
            ttl_seconds: Default TTL in seconds (default: 1 hour)
            cleanup_interval: How often to check for expired entries (default: 5 minutes)
        """
        self.name = name
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval = cleanup_interval
        self._data: Dict[str, CacheEntry[T]] = {}
        self._lock = threading.RLock()
        self._last_cleanup = time.time()
        
    def get(self, key: str) -> Optional[T]:
        """Get an item from the cache, returning None if not found or expired."""
        with self._lock:
            self._maybe_cleanup()
            
            if key not in self._data:
                return None
                
            entry = self._data[key]
            if entry.is_expired():
                del self._data[key]
                return None
                
            return entry.value
            
    def set(self, key: str, value: T, ttl_seconds: Optional[int] = None) -> None:
        """Set an item in the cache with optional custom TTL."""
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        
        with self._lock:
            self._maybe_cleanup()
            self._data[key] = CacheEntry(value, ttl)
            
    def delete(self, key: str) -> None:
        """Delete an item from the cache."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                
    def clear(self) -> None:
        """Clear all items from the cache."""
        with self._lock:
            self._data.clear()
            
    def _maybe_cleanup(self) -> None:
        """Clean up expired entries if cleanup_interval has passed."""
        now = time.time()
        if now - self._last_cleanup > self.cleanup_interval:
            self._cleanup()
            self._last_cleanup = now
            
    def _cleanup(self) -> None:
        """Remove all expired entries from the cache."""
        expired_keys = [k for k, v in self._data.items() if v.is_expired()]
        for key in expired_keys:
            del self._data[key]
            
        if expired_keys:
            logger.info(f"Cleaned up {len(expired_keys)} expired entries from {self.name} cache")
            
    def __len__(self) -> int:
        """Return the number of items in the cache."""
        with self._lock:
            return len(self._data)
            
    def stats(self) -> Dict[str, Any]:
        """Return statistics about the cache."""
        with self._lock:
            return {
                "name": self.name,
                "size": len(self._data),
                "ttl_seconds": self.ttl_seconds,
                "cleanup_interval": self.cleanup_interval,
                "last_cleanup": self._last_cleanup,
            }

def cached(cache: Cache, key_fn: Callable = None):
    """Decorator to cache function results.
    
    Args:
        cache: The cache instance to use
        key_fn: Optional function to generate a cache key from the arguments
               If not provided, uses a tuple of all args and kwargs
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                # Simple default key generation
                key = str((func.__name__, args, frozenset(kwargs.items())))
                
            # Check cache
            cached_result = cache.get(key)
            if cached_result is not None:
                logger.debug(f"Cache hit for {func.__name__}")
                return cached_result
                
            # Cache miss, execute function
            logger.debug(f"Cache miss for {func.__name__}")
            result = func(*args, **kwargs)
            
            # Store in cache
            cache.set(key, result)
            return result
        return wrapper
    return decorator

# Global cache instances
schema_cache = Cache[Dict[str, Any]]("schema", ttl_seconds=3600*24)  # 1 day for schemas
llm_cache = Cache[str]("llm", ttl_seconds=3600)  # 1 hour for LLM responses
playbook_cache = Cache[Tuple[str, str]]("playbook", ttl_seconds=3600*24*7)  # 1 week for generated playbooks