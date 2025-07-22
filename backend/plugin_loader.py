"""Plugin Loader for Relia OSS.

Loads JSON schemas from the base `schemas/` directory, then overlays any
same-named files from `plugins/`, allowing custom module definitions.

Features:
- Caching of schemas to improve performance
- Lazy loading option to defer loading until needed
- Validation of schema format
"""
import json
import os
import logging
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, Set
from datetime import datetime

from .cache import schema_cache, cached

# Configure logger
logger = logging.getLogger(__name__)

def _get_schema_hash(base_dir: Path, plugin_dir: Optional[Path] = None) -> str:
    """Generate a hash of schema directory contents for cache invalidation."""
    hasher = hashlib.md5()
    
    # Add base directory files
    if base_dir.exists():
        for schema_file in sorted(base_dir.glob("*.json")):
            mtime = os.path.getmtime(schema_file)
            hasher.update(f"{schema_file.name}:{mtime}".encode())
    
    # Add plugin directory files
    if plugin_dir and plugin_dir.exists():
        for plugin_file in sorted(plugin_dir.glob("*.json")):
            mtime = os.path.getmtime(plugin_file)
            hasher.update(f"{plugin_file.name}:{mtime}".encode())
    
    return hasher.hexdigest()

def _load_schema_file(file_path: Path) -> Optional[Dict[str, Any]]:
    """Load and validate a single schema file."""
    try:
        schema = json.loads(file_path.read_text(encoding="utf-8"))
        
        # Basic validation
        if not isinstance(schema, dict) or 'options' not in schema:
            logger.warning(f"Invalid schema format in {file_path.name}, missing 'options'")
            return None
            
        return schema
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in {file_path.name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error loading schema {file_path.name}: {e}")
        return None

@cached(schema_cache, key_fn=lambda base_dir, plugin_dir, force_reload=False, lazy=False: 
        "schemas:" + _get_schema_hash(base_dir, plugin_dir))
def load_schemas(
    base_dir: Path,
    plugin_dir: Path | None = None,
    force_reload: bool = False,
    lazy: bool = False
) -> Dict[str, Any]:
    """Load and merge module schemas from base and plugin directories.
    
    Args:
        base_dir: Base directory for schema files
        plugin_dir: Optional directory for plugin schema files
        force_reload: Force reloading even if cached
        lazy: If True, return a lazy-loading proxy
        
    Returns:
        Dictionary of schema objects indexed by name
    """
    # If force_reload, clear the cache
    if force_reload:
        schema_cache.delete("schemas:" + _get_schema_hash(base_dir, plugin_dir))
    
    # Check if this is a lazy load request
    if lazy:
        return LazySchemaLoader(base_dir, plugin_dir)
    
    logger.info(f"Loading schemas from {base_dir} and {plugin_dir}")
    start_time = datetime.now()
    schemas: Dict[str, Any] = {}
    loaded_count = 0
    error_count = 0

    # Load base schemas
    if base_dir.exists():
        for schema_file in base_dir.glob("*.json"):
            key = schema_file.stem
            schema = _load_schema_file(schema_file)
            if schema:
                schemas[key] = schema
                loaded_count += 1
            else:
                error_count += 1

    # Overlay plugin schemas
    if plugin_dir and plugin_dir.exists():
        for plugin_file in plugin_dir.glob("*.json"):
            key = plugin_file.stem
            schema = _load_schema_file(plugin_file)
            if schema:
                schemas[key] = schema
                loaded_count += 1
            else:
                error_count += 1
    
    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"Loaded {loaded_count} schemas in {duration:.2f}s ({error_count} errors)")
    
    return schemas

class LazySchemaLoader:
    """Lazy-loading proxy for schemas.
    
    Only loads individual schemas when they are accessed.
    """
    
    def __init__(self, base_dir: Path, plugin_dir: Optional[Path] = None):
        """Initialize the lazy loader.
        
        Args:
            base_dir: Base directory for schema files
            plugin_dir: Optional directory for plugin schema files
        """
        self.base_dir = base_dir
        self.plugin_dir = plugin_dir
        self._loaded_schemas: Dict[str, Any] = {}
        self._available_keys: Optional[Set[str]] = None
    
    def _get_available_keys(self) -> Set[str]:
        """Get the set of available schema keys without loading content."""
        if self._available_keys is not None:
            return self._available_keys
            
        keys = set()
        
        # Check base schemas
        if self.base_dir.exists():
            keys.update(f.stem for f in self.base_dir.glob("*.json"))
        
        # Check plugin schemas
        if self.plugin_dir and self.plugin_dir.exists():
            keys.update(f.stem for f in self.plugin_dir.glob("*.json"))
            
        self._available_keys = keys
        return keys
    
    def _load_schema(self, key: str) -> Optional[Dict[str, Any]]:
        """Load a specific schema by key."""
        # Check if it's already loaded
        if key in self._loaded_schemas:
            return self._loaded_schemas[key]
            
        # Try loading from plugin dir first (takes precedence)
        if self.plugin_dir and self.plugin_dir.exists():
            plugin_path = self.plugin_dir / f"{key}.json"
            if plugin_path.exists():
                schema = _load_schema_file(plugin_path)
                if schema:
                    self._loaded_schemas[key] = schema
                    return schema
        
        # Try loading from base dir
        if self.base_dir.exists():
            base_path = self.base_dir / f"{key}.json"
            if base_path.exists():
                schema = _load_schema_file(base_path)
                if schema:
                    self._loaded_schemas[key] = schema
                    return schema
        
        return None
    
    def __getitem__(self, key: str) -> Dict[str, Any]:
        """Get a schema by key, loading it if needed."""
        schema = self._load_schema(key)
        if schema is None:
            raise KeyError(f"Schema '{key}' not found")
        return schema
    
    def __contains__(self, key: str) -> bool:
        """Check if a schema exists."""
        return key in self._get_available_keys()
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a schema by key, returning default if not found."""
        try:
            return self[key]
        except KeyError:
            return default
    
    def keys(self) -> Set[str]:
        """Get the set of available schema keys."""
        return self._get_available_keys()
