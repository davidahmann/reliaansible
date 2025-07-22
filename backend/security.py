"""Security utilities for Relia OSS Backend.

This module provides security middleware and utilities for the FastAPI backend,
including CSRF protection, secure headers, and input validation.
"""
import secrets
import logging
import time
from typing import Optional, List
import re

from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware


# Configure module logger
logger = logging.getLogger(__name__)

# Constants
CSRF_COOKIE_NAME = "relia_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_BYTES = 32  # 256 bits

class CSRFProtectionError(Exception):
    """Raised when CSRF protection fails."""
    pass

class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware for CSRF protection using double-submit cookie pattern."""
    
    def __init__(
        self, 
        app,
        secret_key: str,
        cookie_name: str = CSRF_COOKIE_NAME,
        header_name: str = CSRF_HEADER_NAME,
        methods: List[str] = None,
        exclude_paths: List[str] = None,
        cookie_secure: bool = True,
        cookie_httponly: bool = True,
        cookie_samesite: str = "lax",
    ):
        """Initialize CSRF middleware.
        
        Args:
            app: The FastAPI application
            secret_key: Secret key for token generation
            cookie_name: Name of the CSRF cookie
            header_name: Name of the CSRF header
            methods: HTTP methods to protect (default: POST, PUT, DELETE, PATCH)
            exclude_paths: List of path prefixes to exclude from protection
            cookie_secure: Whether to set the secure flag on cookies
            cookie_httponly: Whether to set the httponly flag on cookies
            cookie_samesite: Value for the samesite cookie flag
        """
        super().__init__(app)
        self.secret_key = secret_key
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.methods = methods or ["POST", "PUT", "DELETE", "PATCH"]
        self.exclude_paths = exclude_paths or []
        self.cookie_secure = cookie_secure
        self.cookie_httponly = cookie_httponly
        self.cookie_samesite = cookie_samesite
        
    async def dispatch(self, request: Request, call_next):
        """Process requests and verify CSRF tokens for state-changing methods."""
        # Skip CSRF check for excluded paths
        path = request.url.path
        if any(path.startswith(prefix) for prefix in self.exclude_paths):
            response = await call_next(request)
            return response
            
        # Skip CSRF check for non-protected methods
        if request.method not in self.methods:
            # For GET requests and other non-protected methods, ensure token exists
            response = await call_next(request)
            # Add or refresh the CSRF token if it doesn't exist
            if self.cookie_name not in request.cookies:
                csrf_token = self._generate_csrf_token()
                response = self._set_csrf_cookie(response, csrf_token)
            return response
            
        # For protected methods, validate CSRF token
        csrf_cookie = request.cookies.get(self.cookie_name)
        csrf_header = request.headers.get(self.header_name)
        
        if not csrf_cookie or not csrf_header:
            logger.warning(f"CSRF protection failed - missing token: cookie={bool(csrf_cookie)}, header={bool(csrf_header)}")
            return Response(
                status_code=status.HTTP_403_FORBIDDEN,
                content="CSRF token missing or invalid",
                media_type="text/plain"
            )
            
        if not self._validate_csrf_tokens(csrf_cookie, csrf_header):
            logger.warning("CSRF token validation failed")
            return Response(
                status_code=status.HTTP_403_FORBIDDEN,
                content="CSRF token missing or invalid",
                media_type="text/plain"
            )
            
        # Token is valid, let the request proceed
        response = await call_next(request)
        
        # Refresh the token
        new_token = self._generate_csrf_token()
        response = self._set_csrf_cookie(response, new_token)
        
        return response
        
    def _generate_csrf_token(self) -> str:
        """Generate a secure random CSRF token."""
        # Convert to a URL-safe string
        return secrets.token_urlsafe(CSRF_TOKEN_BYTES)
        
    def _validate_csrf_tokens(self, cookie_token: str, header_token: str) -> bool:
        """Validate that the cookie and header tokens match."""
        # Simple equality check (double-submit cookie pattern)
        return cookie_token == header_token
        
    def _set_csrf_cookie(self, response: Response, token: str) -> Response:
        """Set the CSRF token cookie on the response."""
        response.set_cookie(
            key=self.cookie_name,
            value=token,
            httponly=self.cookie_httponly,
            secure=self.cookie_secure, 
            samesite=self.cookie_samesite,
            max_age=86400  # 24 hours
        )
        return response

class SecureHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware to add security headers to responses."""
    
    def __init__(
        self,
        app,
        csp_policy: Optional[str] = None,
        hsts_enabled: bool = True,
        hsts_max_age: int = 31536000,  # 1 year in seconds
        frame_deny: bool = True,
        content_type_nosniff: bool = True,
        xss_protection: bool = True,
        cache_control: Optional[str] = "no-store, max-age=0",
        permitted_cross_domain_policies: str = "none",
    ):
        """Initialize secure headers middleware.
        
        Args:
            app: The FastAPI application
            csp_policy: Content Security Policy string
            hsts_enabled: Whether to enable HSTS
            hsts_max_age: HSTS max age in seconds
            frame_deny: Whether to deny framing (X-Frame-Options: DENY)
            content_type_nosniff: Whether to prevent MIME type sniffing
            xss_protection: Whether to enable XSS protection header
            cache_control: Cache-Control header value
            permitted_cross_domain_policies: X-Permitted-Cross-Domain-Policies value
        """
        super().__init__(app)
        self.csp_policy = csp_policy
        self.hsts_enabled = hsts_enabled
        self.hsts_max_age = hsts_max_age
        self.frame_deny = frame_deny
        self.content_type_nosniff = content_type_nosniff
        self.xss_protection = xss_protection
        self.cache_control = cache_control
        self.permitted_cross_domain_policies = permitted_cross_domain_policies
        
    async def dispatch(self, request: Request, call_next):
        """Add security headers to responses."""
        response = await call_next(request)
        
        # Add Content-Security-Policy header if configured
        if self.csp_policy:
            response.headers["Content-Security-Policy"] = self.csp_policy
            
        # Add HSTS header if enabled
        if self.hsts_enabled and request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = f"max-age={self.hsts_max_age}; includeSubDomains; preload"
            
        # Add X-Frame-Options header if enabled
        if self.frame_deny:
            response.headers["X-Frame-Options"] = "DENY"
            
        # Add X-Content-Type-Options header if enabled
        if self.content_type_nosniff:
            response.headers["X-Content-Type-Options"] = "nosniff"
            
        # Add X-XSS-Protection header if enabled
        if self.xss_protection:
            response.headers["X-XSS-Protection"] = "1; mode=block"
            
        # Add Cache-Control header if configured
        if self.cache_control:
            response.headers["Cache-Control"] = self.cache_control
            
        # Add X-Permitted-Cross-Domain-Policies header
        response.headers["X-Permitted-Cross-Domain-Policies"] = self.permitted_cross_domain_policies
        
        return response

# Path traversal protection
def is_safe_path(path: str, base_dir: str) -> bool:
    """Check if a path is safe and doesn't traverse outside base_dir."""
    import os
    from pathlib import Path
    
    try:
        # Convert to absolute paths using Path objects for safer handling
        base_path = Path(base_dir).resolve()
        
        # Handle both absolute and relative paths
        if os.path.isabs(path):
            check_path = Path(path).resolve()
        else:
            check_path = Path(os.path.normpath(os.path.join(str(base_path), path))).resolve()
        
        # Make sure base_path exists
        if not base_path.exists():
            return False
            
        # Check if the resolved path starts with the base path
        return str(check_path).startswith(str(base_path))
    except Exception:
        # Any errors during path resolution should be treated as unsafe
        return False

# Regular expressions for input validation
SAFE_STRING_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]+$')

def is_safe_string(s: str) -> bool:
    """Check if a string contains only safe characters (alphanumeric + underscore, hyphen, period)."""
    return bool(SAFE_STRING_PATTERN.match(s))

# ID pattern for UUID and similar identifiers
ID_PATTERN = re.compile(r'^[a-f0-9\-]+$')

def is_valid_id(id_str: str) -> bool:
    """Validate that a string is a valid ID (UUID format)."""
    return bool(ID_PATTERN.match(id_str))

# Email pattern
EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

def is_valid_email(email: str) -> bool:
    """Validate that a string is a valid email address."""
    return bool(EMAIL_PATTERN.match(email))

# URL pattern
URL_PATTERN = re.compile(r'^https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+')

def is_valid_url(url: str) -> bool:
    """Validate that a string is a valid URL."""
    return bool(URL_PATTERN.match(url))

# Rate limiting class (simple in-memory implementation)
class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self, limit: int = 60, window: int = 60):
        """Initialize rate limiter.
        
        Args:
            limit: Maximum number of requests in the window
            window: Time window in seconds
        """
        self.limit = limit
        self.window = window
        self.requests = {}  # key -> [(timestamp, count)]
        
    def is_allowed(self, key: str) -> bool:
        """Check if a request from the key is allowed.
        
        Args:
            key: Identifier for the client (e.g., IP address)
            
        Returns:
            True if the request is allowed, False if rate limit exceeded
        """
        current_time = time.time()
        
        # Clean up old entries
        if key in self.requests:
            self.requests[key] = [
                (ts, count) for ts, count in self.requests[key]
                if current_time - ts < self.window
            ]
        else:
            self.requests[key] = []
            
        # Count recent requests
        total_requests = sum(count for _, count in self.requests[key])
        
        # Check if limit exceeded
        if total_requests >= self.limit:
            return False
            
        # Record this request
        self.requests[key].append((current_time, 1))
        return True
        
    def get_remaining(self, key: str) -> int:
        """Get the number of remaining requests allowed.
        
        Args:
            key: Identifier for the client
            
        Returns:
            Number of remaining requests in the current window
        """
        current_time = time.time()
        
        # Clean up old entries
        if key in self.requests:
            self.requests[key] = [
                (ts, count) for ts, count in self.requests[key]
                if current_time - ts < self.window
            ]
            total_requests = sum(count for _, count in self.requests[key])
            return max(0, self.limit - total_requests)
        
        return self.limit