# Relia Caching System

This document provides an overview of the caching system implemented in Relia OSS.

## Caching Architecture

The caching system in Relia OSS is designed to improve performance by reducing unnecessary computation and API calls. It consists of three main types of caches:

1. **Schema Cache**: Stores JSON schemas for Ansible modules to reduce disk I/O
2. **LLM Cache**: Stores responses from LLM providers to reduce API calls and costs
3. **Playbook Cache**: Stores generated playbooks and their lint results

## Cache Configuration

Each cache has its own default time-to-live (TTL) settings:

- Schema cache: 24 hours
- LLM cache: 1 hour
- Playbook cache: 7 days

These TTLs can be overridden when setting values in the cache.

## Using the Cache System

### Basic Usage

The cache system provides a simple key-value interface:

```python
from backend.cache import schema_cache, llm_cache, playbook_cache

# Store a value
llm_cache.set("my_key", "my_value")

# Retrieve a value
value = llm_cache.get("my_key")  # Returns None if not found or expired

# Delete a value
llm_cache.delete("my_key")

# Clear the entire cache
llm_cache.clear()
```

### Using the @cached Decorator

For functions that you want to cache, you can use the `@cached` decorator:

```python
from backend.cache import schema_cache, cached

@cached(schema_cache)
def expensive_function(arg1, arg2):
    # This result will be cached based on the function name and arguments
    return compute_expensive_result(arg1, arg2)
```

You can also provide a custom key function:

```python
@cached(schema_cache, key_fn=lambda arg1, arg2: f"custom:{arg1}:{arg2}")
def another_function(arg1, arg2):
    # Cache key will be "custom:arg1:arg2"
    return compute_result(arg1, arg2)
```

## Cache Configuration Options

### Thread Safety

All caches are thread-safe, using a reentrant lock to protect concurrent access.

### Automatic Cleanup

Caches have an automatic cleanup mechanism that runs periodically to remove expired entries. The default cleanup interval is 5 minutes, but this can be customized when creating a cache.

### Cache Statistics

You can obtain statistics about each cache:

```python
stats = llm_cache.stats()
print(f"Cache size: {stats['size']}")
print(f"Last cleanup: {stats['last_cleanup']}")
```

## Cache Control API

The system provides admin endpoints for cache inspection and management:

- `GET /admin/cache/stats` - Get statistics about all caches
- `POST /admin/cache/clear` - Clear one or more caches

Both endpoints require the `admin` role.

## Disabling Caching

Caching can be disabled for:

1. LLM clients, by passing `use_cache=False` when initializing:
   ```python
   client = OpenAIClient(use_cache=False)
   ```

2. PlaybookService, by passing `use_cache=False` when initializing:
   ```python
   service = PlaybookService(llm_client, use_cache=False)
   ```

## Implementation Details

### Cache Keys

- Schema cache keys are based on a hash of the directory contents
- LLM cache keys are based on the model name and a hash of the prompt
- Playbook cache keys are based on a hash of the module and prompt

### Cache Data Structure

The cache is implemented as a dictionary of `CacheEntry` objects, each containing:

- The cached value
- The expiration timestamp

### Performance Considerations

- The cache system is designed to be memory-efficient
- Expired entries are lazily cleaned up
- The caching overhead is negligible compared to the cost of LLM API calls

## Future Improvements

Potential improvements to the caching system:

1. Persistent caching to disk for LLM responses
2. Distributed caching for multi-instance deployments
3. Rate limiting based on cache hit/miss rates
4. Cache warm-up for frequently used schemas