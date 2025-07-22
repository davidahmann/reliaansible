"""JWT Authentication for Relia OSS with token validation.

* If RELIA_JWT_SECRET is set, API calls require a Bearer JWT signed with HS256.
* If unset, auth is bypassed (local‑dev mode).
* Token payload must include `sub` (user id), `roles` (list[str]), and `exp` (expiration).
* Use `role_required(<role>)` dependency to enforce RBAC.
"""
import time
import logging
import secrets
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from .config import settings
from .secrets import get_secret

# Configure logger
logger = logging.getLogger(__name__)

# Constants
# Try to get JWT secret from secrets manager first, then fallback to settings
SECRET = get_secret("RELIA_JWT_SECRET") or settings.JWT_SECRET
ALGORITHM = "HS256"
TOKEN_EXPIRY = 24  # token expiry in hours
bearer_scheme = HTTPBearer(auto_error=False)

class AuthError(Exception):
    """Base exception for authentication errors."""
    pass

def create_token(user_id: str, roles: List[str], expiry_hours: int = TOKEN_EXPIRY) -> Dict[str, str]:
    """Create new JWT access and refresh tokens with expiration.
    
    Returns:
        Dictionary with access_token and refresh_token
    """
    # Don't allow token creation without a proper secret
    if not SECRET:
        if settings.ENV == "prod":
            logger.error("Attempted to create JWT token without a secret in production mode")
            raise AuthError("Cannot create JWT token: No secret key configured in production")
        else:
            logger.warning("Creating token with no secret in development mode - this is insecure")
    
    # Create a unique token ID (jti)
    jti = secrets.token_hex(16)
    
    # Current timestamp
    now = datetime.utcnow()
    
    # Access token - short lived (default: 1 hour)
    access_expiration = now + timedelta(hours=1)
    access_payload = {
        "sub": user_id,
        "roles": roles,
        "exp": access_expiration.timestamp(),
        "iat": now.timestamp(),
        "jti": jti,
        "type": "access"
    }
    
    # Refresh token - longer lived (default: TOKEN_EXPIRY)
    refresh_expiration = now + timedelta(hours=expiry_hours)
    refresh_payload = {
        "sub": user_id,
        "exp": refresh_expiration.timestamp(),
        "iat": now.timestamp(),
        "jti": jti + "-refresh",
        "type": "refresh"
    }
    
    # Use the configured secret, don't fall back to insecure default in production
    secret_key = SECRET
    if not secret_key:
        # Only allow fallback in non-production environments
        if settings.ENV != "prod":
            secret_key = "insecure-dev-mode"
        else:
            # This should never happen due to the earlier check, but as a safeguard
            raise AuthError("Cannot create JWT token: No secret key configured in production")
            
    access_token = jwt.encode(access_payload, secret_key, algorithm=ALGORITHM)
    refresh_token = jwt.encode(refresh_payload, secret_key, algorithm=ALGORITHM)
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 3600  # 1 hour in seconds
    }

def verify_token(token: str) -> Dict:
    """Verify JWT token and return payload if valid."""
    try:
        # First parse without verification to get token type
        unverified_payload = jwt.decode(token, options={"verify_signature": False})
        token_type = unverified_payload.get("type", "access")
        
        # Determine which secret to use for verification
        secret_key = SECRET
        if not secret_key:
            # Only allow fallback in non-production environments
            if settings.ENV != "prod":
                secret_key = "insecure-dev-mode"
            else:
                logger.error("Attempted to verify JWT token without a secret in production mode")
                raise AuthError("Cannot verify JWT token: No secret key configured in production")
                
        # Now fully verify the token
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        
        # Check if token is expired
        expiration = payload.get("exp")
        if expiration and expiration < time.time():
            logger.warning(f"Expired token attempted: {payload.get('sub')}")
            raise AuthError("Token has expired")
            
        # Validate required fields
        if not payload.get("sub"):
            raise AuthError("Token missing 'sub' claim")
        
        # Check token type-specific requirements
        if token_type == "access":
            if not isinstance(payload.get("roles", []), list):
                raise AuthError("Access token has invalid 'roles' claim")
        elif token_type == "refresh":
            # Refresh tokens don't need roles, but should have jti
            if not payload.get("jti"):
                raise AuthError("Refresh token missing 'jti' claim")
        else:
            raise AuthError(f"Unknown token type: {token_type}")
        
        return payload
        
    except jwt.PyJWTError as e:
        logger.error(f"JWT validation error: {e}")
        raise AuthError(f"Invalid token: {e}")
        
def refresh_access_token(refresh_token: str) -> Dict[str, str]:
    """Generate a new access token using a valid refresh token."""
    try:
        # Verify the refresh token
        payload = verify_token(refresh_token)
        
        # Ensure it's actually a refresh token
        if payload.get("type") != "refresh":
            raise AuthError("Not a valid refresh token")
        
        # Create a new access token
        user_id = payload.get("sub")
        
        # We need to retrieve user roles from somewhere
        # For simplicity, we'll grant basic roles here
        # In a real system, you would retrieve this from a database
        roles = ["generator", "tester"]
        
        # Create only an access token (not a new refresh token)
        now = datetime.utcnow()
        access_expiration = now + timedelta(hours=1)
        access_payload = {
            "sub": user_id,
            "roles": roles,
            "exp": access_expiration.timestamp(),
            "iat": now.timestamp(),
            "jti": secrets.token_hex(16),
            "type": "access"
        }
        
        # Use the configured secret, don't fall back to insecure default in production
        secret_key = SECRET
        if not secret_key:
            # Only allow fallback in non-production environments
            if settings.ENV != "prod":
                secret_key = "insecure-dev-mode"
            else:
                # This should never happen due to the earlier checks, but as a safeguard
                raise AuthError("Cannot create JWT token: No secret key configured in production")
                
        access_token = jwt.encode(access_payload, secret_key, algorithm=ALGORITHM)
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 3600  # 1 hour in seconds
        }
    except AuthError:
        # Re-raise auth errors
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise AuthError(f"Failed to refresh token: {e}")

def log_auth_attempt(request: Request, success: bool, user_id: Optional[str] = None, error: Optional[str] = None):
    """Log authentication attempts for security auditing."""
    client_ip = request.client.host if request and request.client else "unknown"
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "client_ip": client_ip,
        "path": request.url.path if request else "unknown",
        "method": request.method if request else "unknown",
        "success": success,
        "user_id": user_id or "anonymous",
    }
    
    if error:
        log_data["error"] = error
        
    if success:
        logger.info(f"Authentication success: user={user_id}, ip={client_ip}, path={request.url.path}")
    else:
        logger.warning(f"Authentication failure: ip={client_ip}, path={request.url.path}, error={error}")

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
) -> Dict:
    """Decode JWT and return payload, or allow anonymous if auth disabled."""
    # If auth is disabled (no secret set), handle based on environment
    if SECRET is None:
        # In production, authentication should never be disabled
        if settings.ENV == "prod":
            logger.error("Authentication disabled in production mode! This is a critical security risk.")
            # In production, refuse to run without authentication
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error: JWT_SECRET must be set in production",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            # Only in dev/test environments, allow default permissions
            logger.warning("Development mode: Authentication disabled, using default permissions")
            return {"sub": "anonymous", "roles": ["generator", "tester"]}
    
    # Require valid credentials in auth-enabled mode
    if not credentials or credentials.scheme.lower() != "bearer":
        log_auth_attempt(request, False, error="Missing or invalid authentication token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = verify_token(credentials.credentials)
        log_auth_attempt(request, True, user_id=payload.get("sub"))
        return payload
    except AuthError as e:
        log_auth_attempt(request, False, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

def role_required(role: str):
    """Dependency to ensure the user has the specified role."""
    def checker(request: Request, user: Dict = Depends(get_current_user)) -> Dict:
        if not user or role not in user.get("roles", []):
            logger.warning(f"Access denied: User {user.get('sub')} missing required role '{role}'")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Role '{role}' required",
            )
        return user
    return checker
