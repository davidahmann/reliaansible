"""Secrets management for Relia OSS.

This module provides a secure way to manage secrets, with support for
multiple backend providers:
1. Environment variables (default)
2. .env files (for local development)
3. AWS Secrets Manager (for production)
4. HashiCorp Vault (for enterprise)

Usage:
    from backend.secrets import get_secret
    db_password = get_secret("DB_PASSWORD")
"""
import os
import logging
import json
import base64
from typing import Optional, Dict, Callable
from functools import lru_cache
from pathlib import Path

import dotenv

# Configure module logger
logger = logging.getLogger(__name__)

# Secret provider backend types
class SecretBackend:
    """Enum-like class for secret backend types."""
    ENV = "env"
    FILE = "file"
    AWS = "aws"
    VAULT = "vault"

# Default backend is environment variables
DEFAULT_BACKEND = SecretBackend.ENV

# Current provider
_current_backend = os.getenv("RELIA_SECRET_BACKEND", DEFAULT_BACKEND)

# Cache for secrets to avoid excessive API calls
_secrets_cache: Dict[str, str] = {}

def _get_from_env(key: str) -> Optional[str]:
    """Get secret from environment variable."""
    return os.environ.get(key)

def _get_from_dotenv(key: str) -> Optional[str]:
    """Get secret from .env file."""
    # Load .env file if exists in current dir or parent dir
    env_path = Path(".env")
    if not env_path.exists():
        env_path = Path("../.env")
    
    if env_path.exists():
        dotenv.load_dotenv(env_path)
        return os.environ.get(key)
    
    return None

def _get_from_aws(key: str) -> Optional[str]:
    """Get secret from AWS Secrets Manager."""
    try:
        import boto3
        from botocore.exceptions import ClientError
        
        # Secret name based on environment
        env = os.getenv("RELIA_ENV", "dev")
        secret_name = f"relia/{env}/{key}"
        
        # Create a Secrets Manager client
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        
        try:
            get_secret_value_response = client.get_secret_value(
                SecretId=secret_name
            )
        except ClientError as e:
            logger.error(f"Error retrieving secret {key} from AWS: {e}")
            return None
            
        # Extract secret value
        if 'SecretString' in get_secret_value_response:
            secret = get_secret_value_response['SecretString']
            # Handle JSON format for grouped secrets
            try:
                secret_json = json.loads(secret)
                if isinstance(secret_json, dict) and key in secret_json:
                    return secret_json[key]
                return secret
            except json.JSONDecodeError:
                return secret
        else:
            # Handle binary secrets (unlikely)
            decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])
            return decoded_binary_secret.decode('utf-8')
    except ImportError:
        logger.error("boto3 not installed - cannot use AWS Secrets Manager")
        return None
    except Exception as e:
        logger.error(f"Error in AWS Secrets Manager: {e}")
        return None

def _get_from_vault(key: str) -> Optional[str]:
    """Get secret from HashiCorp Vault."""
    try:
        import hvac
        
        # Vault connection parameters
        vault_addr = os.getenv("VAULT_ADDR")
        vault_token = os.getenv("VAULT_TOKEN")
        
        if not vault_addr or not vault_token:
            logger.error("Vault credentials not found in environment")
            return None
            
        # Connect to Vault
        client = hvac.Client(url=vault_addr, token=vault_token)
        
        # Check if authenticated
        if not client.is_authenticated():
            logger.error("Failed to authenticate with Vault")
            return None
            
        # Construct path in vault
        env = os.getenv("RELIA_ENV", "dev")
        mount_point = "secret"  # Default mount point
        path = f"relia/{env}"
        
        try:
            # Read secret
            secret_response = client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=mount_point
            )
            
            # Extract data
            secret_data = secret_response["data"]["data"]
            if key in secret_data:
                return str(secret_data[key])
            else:
                logger.warning(f"Key {key} not found in Vault at {path}")
                return None
        except Exception as e:
            logger.error(f"Error retrieving secret from Vault: {e}")
            return None
    except ImportError:
        logger.error("hvac not installed - cannot use HashiCorp Vault")
        return None
    except Exception as e:
        logger.error(f"Error in Vault secret manager: {e}")
        return None

# Map of backend types to getter functions
_backend_getters: Dict[str, Callable[[str], Optional[str]]] = {
    SecretBackend.ENV: _get_from_env,
    SecretBackend.FILE: _get_from_dotenv,
    SecretBackend.AWS: _get_from_aws,
    SecretBackend.VAULT: _get_from_vault,
}

@lru_cache(maxsize=128)
def get_secret(key: str, default: str = None) -> Optional[str]:
    """Get a secret from the configured backend.
    
    Args:
        key: The key to look up
        default: Optional default value if not found
        
    Returns:
        The secret value or default if not found
    """
    # Check cache first to avoid repeated API calls
    if key in _secrets_cache:
        return _secrets_cache[key]
    
    # Get the value from the primary backend
    primary_getter = _backend_getters.get(_current_backend)
    if not primary_getter:
        logger.error(f"Invalid secret backend: {_current_backend}")
        return default
        
    value = primary_getter(key)
    
    # If not found, try environment as a fallback
    if value is None and _current_backend != SecretBackend.ENV:
        value = _get_from_env(key)
    
    # If still not found, try .env file as a final fallback
    if value is None and _current_backend not in [SecretBackend.ENV, SecretBackend.FILE]:
        value = _get_from_dotenv(key)
    
    # Cache the result
    if value is not None:
        _secrets_cache[key] = value
        
    return value if value is not None else default

def initialize_secrets(backend: str = None) -> None:
    """Initialize the secrets manager with specified backend.
    
    Args:
        backend: The backend type to use (env, file, aws, or vault)
    """
    global _current_backend
    
    # Set the backend
    if backend:
        _current_backend = backend
    else:
        _current_backend = os.getenv("RELIA_SECRET_BACKEND", DEFAULT_BACKEND)
    
    logger.info(f"Initialized secrets manager with backend: {_current_backend}")
    
    # Pre-load common secrets to validate configuration
    if _current_backend == SecretBackend.AWS:
        # Check AWS credentials
        aws_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_region = os.getenv("AWS_REGION")
        if not aws_key or not aws_region:
            logger.warning("AWS credentials not properly configured")
    
    elif _current_backend == SecretBackend.VAULT:
        # Check Vault credentials
        vault_addr = os.getenv("VAULT_ADDR")
        vault_token = os.getenv("VAULT_TOKEN")
        if not vault_addr or not vault_token:
            logger.warning("Vault credentials not properly configured")

def get_all_secrets(prefix: str = None) -> Dict[str, str]:
    """Get all secrets with an optional prefix filter.
    
    Args:
        prefix: Optional prefix to filter secret keys
        
    Returns:
        Dictionary of secret keys and values
    """
    # This only works for environment variable backend for security reasons
    if _current_backend == SecretBackend.ENV:
        if prefix:
            return {k: v for k, v in os.environ.items() if k.startswith(prefix)}
        else:
            return dict(os.environ)
    else:
        logger.warning(f"get_all_secrets() only supported for 'env' backend, not {_current_backend}")
        return {}

def clear_cache() -> None:
    """Clear the secrets cache."""
    global _secrets_cache
    _secrets_cache = {}
    get_secret.cache_clear()
    logger.info("Secrets cache cleared")