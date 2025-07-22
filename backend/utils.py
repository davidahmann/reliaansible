"""Utility functions for Relia backend."""
import os
import re
from pathlib import Path
from typing import Optional, Union
import logging

logger = logging.getLogger(__name__)

def validate_safe_path(base_dir: Union[str, Path], user_path: str, allow_absolute: bool = False) -> Optional[Path]:
    """
    Validate that a user-provided path is safe and does not traverse outside the base directory.
    
    Args:
        base_dir: The base directory that paths should be contained within
        user_path: The user-provided path to validate
        allow_absolute: Whether to allow absolute paths (default: False)
        
    Returns:
        A Path object if the path is safe, None otherwise
    """
    # Convert base_dir to a Path object and resolve to absolute path
    base_dir = Path(base_dir).resolve()
    
    # Check if base_dir exists
    if not base_dir.exists():
        logger.error(f"Base directory does not exist: {base_dir}")
        return None
    
    # Check if user_path is empty
    if not user_path:
        logger.error("Empty path provided")
        return None
    
    # Normalize path to handle different separators across platforms
    user_path = os.path.normpath(user_path)
    
    # Check for path traversal attempts using common patterns
    if re.search(r'\.\./', user_path) or '..' in Path(user_path).parts:
        logger.warning(f"Path traversal attempt detected: {user_path}")
        return None
    
    # Check for absolute paths if not allowed
    if os.path.isabs(user_path) and not allow_absolute:
        logger.warning(f"Absolute path provided but not allowed: {user_path}")
        return None
    
    try:
        # Convert to Path object and resolve to absolute path
        if os.path.isabs(user_path):
            # For absolute paths, verify they're within the base directory
            full_path = Path(user_path).resolve()
            # Check if path is within the base directory
            if not str(full_path).startswith(str(base_dir)):
                logger.warning(f"Path escapes base directory: {full_path} not in {base_dir}")
                return None
        else:
            # For relative paths, join with base directory and resolve
            full_path = (base_dir / user_path).resolve()
            # Check if path is within the base directory
            if not str(full_path).startswith(str(base_dir)):
                logger.warning(f"Path escapes base directory: {full_path} not in {base_dir}")
                return None
    except (ValueError, OSError) as e:
        logger.error(f"Error resolving path {user_path}: {e}")
        return None
    
    return full_path

def is_safe_file_name(filename: str) -> bool:
    """
    Check if a filename is safe (no path traversal, valid characters only).
    
    Args:
        filename: The filename to check
        
    Returns:
        True if filename is safe, False otherwise
    """
    # Check for empty filename
    if not filename:
        return False
    
    # Check for path separators
    if '/' in filename or '\\' in filename:
        return False
    
    # Check for parent directory references
    if '..' in filename:
        return False
    
    # Check for hidden files (starting with .)
    if filename.startswith('.'):
        return False
    
    # Only allow alphanumeric, underscore, hyphen, and period
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', filename):
        return False
    
    return True