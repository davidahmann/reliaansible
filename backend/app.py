"""FastAPI backend for Relia OSS with centralized config, JWT RBAC, and stubbed endpoints."""
from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status, BackgroundTasks, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
import structlog
import jwt
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .auth import role_required
from .llm_adapter import LLMClient, get_client, LLMError, LLMValidationError, LLMTimeoutError
from .plugin_loader import load_schemas
from .services.playbook_service import PlaybookService, PlaybookValidationError, PlaybookExecutionError
from .cache import schema_cache, llm_cache, playbook_cache
from . import database
from . import tasks
from . import monitoring
from .logging_handlers import setup_logging, AccessLogMiddleware
from .security import CSRFMiddleware, SecureHeadersMiddleware
from .secrets import get_secret

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

# Configure application logging
app_logger = setup_logging()

app = FastAPI(
    title="Relia OSS Backend",
    version=settings.VERSION,
    description="Relia API for generating, validating and managing Ansible playbooks",
    docs_url="/api/docs",  # OpenAPI documentation
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc",
)

# Add middlewares
app.add_middleware(GZipMiddleware, minimum_size=1000)

# HTTPS redirect middleware for production environments
class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only redirect in production environment and when not already HTTPS
        if settings.ENV == "prod" and settings.ENFORCE_HTTPS and not request.url.scheme == "https":
            # Get the host from the request
            host = request.headers.get("host", "").split(":")[0]
            
            # Create the redirect URL
            redirect_url = f"https://{host}{request.url.path}"
            if request.url.query:
                redirect_url += f"?{request.url.query}"
                
            # Log the redirect
            logger.info(f"HTTPS redirect: {request.url} -> {redirect_url}")
            
            # Return a 308 Permanent Redirect
            from fastapi.responses import Response
            return Response(
                status_code=status.HTTP_308_PERMANENT_REDIRECT,
                headers={"location": redirect_url}
            )
            
        return await call_next(request)

# Add HTTPS redirect middleware if enabled in settings
if settings.ENV == "prod" and settings.ENFORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)
    logger.info("HTTPS redirect middleware enabled")
    
# HSTS middleware to enforce HTTPS in browsers
class HSTSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Only add HSTS header in production and if enabled
        if settings.ENV == "prod" and settings.HSTS_ENABLED:
            response.headers["Strict-Transport-Security"] = f"max-age={settings.HSTS_MAX_AGE}; includeSubDomains; preload"
            
        return response

# Add HSTS middleware if enabled in settings
if settings.ENV == "prod" and settings.HSTS_ENABLED:
    app.add_middleware(HSTSMiddleware)
    logger.info("HSTS middleware enabled")

# Configure CORS with more restrictive settings
allowed_origins = os.getenv(
    "RELIA_CORS_ORIGINS", 
    "http://localhost:8000,http://localhost:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-ID"],
    expose_headers=["X-Total-Count", "X-Request-ID"],
    max_age=600  # Cache preflight requests for 10 minutes
)

# Rate limiting middleware with distributed attack protection
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.request_counts = {}
        self.lock = threading.RLock()
        self.last_cleanup = time.time()
        
        # Track requests by path to better detect targeted attacks
        self.path_counts = {}
        
        # Global rate limit (across all IPs)
        self.global_rate_limit = requests_per_minute * 5  # 5x the per-IP limit
        self.global_request_count = 0
        self.global_reset_time = time.time() + 60
        
    async def dispatch(self, request: Request, call_next):
        current_time = time.time()
        path = request.url.path
        client_ip = request.client.host
        
        # Perform periodic cleanup (every 10 seconds)
        with self.lock:
            if current_time - self.last_cleanup > 10:
                self._cleanup_counters(current_time)
                self.last_cleanup = current_time
        
        # Check global rate limit (protects against distributed attacks)
        with self.lock:
            if current_time > self.global_reset_time:
                self.global_request_count = 0
                self.global_reset_time = current_time + 60
                
            self.global_request_count += 1
            if self.global_request_count > self.global_rate_limit:
                logger.warning(f"Global rate limit exceeded: {self.global_request_count} requests")
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Server is experiencing heavy load. Please try again later."},
                    headers={"Retry-After": str(int(self.global_reset_time - current_time))}
                )
        
        # Check IP-based rate limit
        with self.lock:
            # Track per IP
            if client_ip not in self.request_counts:
                self.request_counts[client_ip] = {
                    "count": 0,
                    "reset_time": current_time + 60
                }
                
            ip_data = self.request_counts[client_ip]
            
            # Reset counter if needed
            if current_time > ip_data["reset_time"]:
                ip_data["count"] = 0
                ip_data["reset_time"] = current_time + 60
                
            # Increment and check
            ip_data["count"] += 1
            
            if ip_data["count"] > self.requests_per_minute:
                logger.warning(f"Rate limit exceeded for IP {client_ip}: {ip_data['count']} requests")
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Rate limit exceeded. Try again later."},
                    headers={"Retry-After": str(int(ip_data["reset_time"] - current_time))}
                )
            
            # Track per path to detect targeted attacks
            path_key = f"{client_ip}:{path}"
            if path_key not in self.path_counts:
                self.path_counts[path_key] = {
                    "count": 0,
                    "reset_time": current_time + 60
                }
                
            path_data = self.path_counts[path_key]
            
            # Reset counter if needed
            if current_time > path_data["reset_time"]:
                path_data["count"] = 0
                path_data["reset_time"] = current_time + 60
                
            # Increment and check (stricter limit for specific endpoints)
            path_data["count"] += 1
            
            # Lower limit for specific endpoints that might be targeted
            path_limit = self.requests_per_minute // 2 if path in ["/auth/token", "/generate"] else self.requests_per_minute
            
            if path_data["count"] > path_limit:
                logger.warning(f"Path-specific rate limit exceeded for {client_ip} on {path}: {path_data['count']} requests")
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too many requests to this endpoint. Try again later."},
                    headers={"Retry-After": str(int(path_data["reset_time"] - current_time))}
                )
        
        return await call_next(request)
        
    def _cleanup_counters(self, current_time: float):
        """Clean up expired counters to prevent memory leaks."""
        # Clean IP counters
        expired_ips = [ip for ip, data in self.request_counts.items() 
                      if current_time > data["reset_time"]]
        for ip in expired_ips:
            del self.request_counts[ip]
            
        # Clean path counters
        expired_paths = [path for path, data in self.path_counts.items() 
                       if current_time > data["reset_time"]]
        for path in expired_paths:
            del self.path_counts[path]

# Metrics middleware
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Process the request
        response = await call_next(request)
        
        # Record metrics (skip health and metrics endpoints)
        path = request.url.path
        if not (path.startswith("/health") or path.startswith("/metrics")):
            metrics = monitoring.get_metrics()
            metrics.record_request(path, response.status_code)
        
        return response

# Add middlewares
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT)
app.add_middleware(MetricsMiddleware)
app.add_middleware(AccessLogMiddleware)

# Get the CSRF secret key from secrets manager or generate one
csrf_secret_key = get_secret("RELIA_CSRF_SECRET") or secrets.token_hex(32)

# Add CSRF protection middleware
app.add_middleware(
    CSRFMiddleware,
    secret_key=csrf_secret_key,
    cookie_secure=settings.SECURE_COOKIES,
    # Exclude paths that don't need CSRF protection
    exclude_paths=[
        "/health",
        "/metrics",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
    ]
)

# Add secure headers middleware
app.add_middleware(
    SecureHeadersMiddleware,
    csp_policy="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
    hsts_enabled=settings.HSTS_ENABLED,
    hsts_max_age=settings.HSTS_MAX_AGE,
)

# Global exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error", 
                     path=request.url.path,
                     method=request.method,
                     error=str(exc),
                     client_ip=request.client.host if request.client else None)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "type": type(exc).__name__}
    )
    
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP Exception: {exc.status_code} - {exc.detail}",
                  path=request.url.path,
                  method=request.method,
                  client_ip=request.client.host if request.client else None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "type": "HTTPException"}
    )
    
@app.exception_handler(jwt.PyJWTError)
async def jwt_exception_handler(request: Request, exc: jwt.PyJWTError):
    logger.warning(f"JWT Error: {str(exc)}",
                  path=request.url.path,
                  method=request.method,
                  client_ip=request.client.host if request.client else None)
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Invalid authentication token", "type": "AuthenticationError"},
        headers={"WWW-Authenticate": "Bearer"}
    )

# ---------------------------------------------------------------------------
# Initialize globals from config
# ---------------------------------------------------------------------------
schemas = load_schemas(settings.SCHEMA_DIR, settings.PLUGIN_DIR)

# Initialize database if enabled
if settings.DB_ENABLED:
    try:
        # Initialize database with connection pool
        database.initialize_database(force_init=True)
        logger.info("Database initialized with connection pool")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        # Continue without database functionality

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=1000, description="Task description to generate Ansible YAML for")
    module: str = Field(..., pattern=r"^[a-z0-9_.]+$", description="Ansible module name (e.g. 'ansible.builtin.copy')")

    @validator("module")
    def validate_module(cls, v):
        """Validate that the module name is properly formatted."""
        if not v:
            raise ValueError("Module name cannot be empty")
        if len(v) > 100:
            raise ValueError("Module name is too long")
        return v

class GenerateResponse(BaseModel):
    playbook_id: str = Field(..., description="Generated playbook ID for reference")
    playbook_yaml: str = Field(..., description="Generated Ansible YAML content")

class PlaybookRequest(BaseModel):
    playbook_id: str = Field(..., pattern=r"^[a-f0-9-]+$", description="UUID of the playbook to operate on")

class LintResponse(BaseModel):
    errors: List[str] = Field([], description="List of linting errors")

class TestResponse(BaseModel):
    status: str = Field(..., description="Test result status ('passed' or 'failed')")
    logs: str = Field(..., description="Test execution logs")

class FeedbackRequest(BaseModel):
    playbook_id: str = Field(..., pattern=r"^[a-f0-9-]+$", description="UUID of the playbook to provide feedback for")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1-5 (1=poor, 5=excellent)")
    comment: Optional[str] = Field(None, max_length=1000, description="Optional feedback comment")

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
def get_llm_client() -> LLMClient:
    """Dependency for getting an LLM client."""
    return get_client()

def get_schema_store() -> Dict[str, Any]:
    """Dependency for accessing the schema store."""
    return schemas

def get_playbook_service(llm_client: LLMClient = Depends(get_llm_client)) -> PlaybookService:
    """Dependency for getting a PlaybookService instance."""
    return PlaybookService(llm_client)

def get_user_id(request: Request) -> str:
    """Get the user ID from the request."""
    # In a real application, this would use JWT auth data
    # For now, we'll use a simple header or default to anonymous
    return request.headers.get("X-User-ID", "anonymous")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/v1/generate",
    response_model=GenerateResponse,
    dependencies=[Depends(role_required("generator"))],
    status_code=status.HTTP_201_CREATED,
    tags=["Playbooks"],
    summary="Generate an Ansible playbook",
    description="Generate an Ansible playbook from natural language using the specified module",
)
async def generate(
    request: Request,
    req: GenerateRequest,
    playbook_service: PlaybookService = Depends(get_playbook_service),
    schemas: Dict[str, Any] = Depends(get_schema_store),
):
    """Generate an Ansible playbook from natural language using the specified module."""
    # Get user ID for telemetry
    user_id = get_user_id(request)
    
    # Log request
    logger.info("Generate request", module=req.module, prompt_length=len(req.prompt), user_id=user_id)
    
    # Find module schema
    key = req.module if req.module in schemas else req.module.replace("ansible.builtin.", "")
    if key not in schemas:
        logger.error("Schema not found", module=req.module)
        
        # Record telemetry for schema not found
        if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
            database.record_telemetry(
                "generate_schema_not_found",
                {"module": req.module},
                user_id=user_id
            )
            
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Schema for module '{req.module}' not found"
        )

    try:
        # Use service to generate playbook
        playbook_id, yaml_out = playbook_service.generate_playbook(
            module=req.module,
            prompt=req.prompt,
            schema=schemas[key],
            user_id=user_id
        )
        
        logger.info("Playbook generated", playbook_id=playbook_id, yaml_size=len(yaml_out))
        return GenerateResponse(playbook_id=playbook_id, playbook_yaml=yaml_out)
        
    except LLMValidationError as e:
        logger.error("LLM validation error", error=str(e))
        
        # Record telemetry for validation error
        if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
            database.record_telemetry(
                "generate_validation_error",
                {"module": req.module, "error": str(e)},
                user_id=user_id
            )
            
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid YAML generated: {e}"
        )
    except LLMTimeoutError as e:
        logger.error("LLM timeout", error=str(e))
        
        # Record telemetry for timeout
        if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
            database.record_telemetry(
                "generate_timeout",
                {"module": req.module, "error": str(e)},
                user_id=user_id
            )
            
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"LLM request timed out: {e}"
        )
    except LLMError as e:
        logger.error("LLM error", error=str(e))
        
        # Record telemetry for LLM error
        if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
            database.record_telemetry(
                "generate_llm_error",
                {"module": req.module, "error": str(e)},
                user_id=user_id
            )
            
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM service error: {e}"
        )

@app.post(
    "/v1/lint",
    response_model=LintResponse,
    dependencies=[Depends(role_required("tester"))],
    tags=["Playbooks"],
    summary="Lint an Ansible playbook",
    description="Lint an existing Ansible playbook using ansible-lint",
)
async def lint(
    request: Request,
    req: PlaybookRequest,
    playbook_service: PlaybookService = Depends(get_playbook_service),
):
    """Lint an Ansible playbook using ansible-lint."""
    # Get user ID for telemetry
    user_id = get_user_id(request)
    
    # Log request
    logger.info("Lint request", playbook_id=req.playbook_id, user_id=user_id)
    
    try:
        # Use service to lint playbook
        errors = playbook_service.lint_playbook(
            playbook_id=req.playbook_id,
            timeout=settings.API_TIMEOUT,
            user_id=user_id
        )
        
        logger.info("Linting complete", playbook_id=req.playbook_id, error_count=len(errors))
        return LintResponse(errors=errors)
        
    except PlaybookValidationError as e:
        logger.error("Playbook validation error", playbook_id=req.playbook_id, error=str(e))
        
        # Record telemetry for validation error
        if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
            database.record_telemetry(
                "lint_validation_error",
                {"playbook_id": req.playbook_id, "error": str(e)},
                user_id=user_id
            )
            
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PlaybookExecutionError as e:
        if "timeout" in str(e).lower():
            logger.error("Linting timeout", playbook_id=req.playbook_id)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Linting process timed out"
            )
        else:
            logger.exception("Linting error", playbook_id=req.playbook_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Linting failed: {e}"
            )

@app.post(
    "/v1/test",
    response_model=TestResponse,
    dependencies=[Depends(role_required("tester"))],
    tags=["Playbooks"],
    summary="Test an Ansible playbook",
    description="Test an existing Ansible playbook using Molecule",
)
async def test(
    request: Request,
    req: PlaybookRequest, 
    background_tasks: BackgroundTasks,
    playbook_service: PlaybookService = Depends(get_playbook_service),
):
    """Test an Ansible playbook using Molecule."""
    # Get user ID for telemetry
    user_id = get_user_id(request)
    
    # Log request
    logger.info("Test request", playbook_id=req.playbook_id, user_id=user_id)
    
    try:
        # Use service to test playbook
        test_status, logs = playbook_service.test_playbook(
            playbook_id=req.playbook_id,
            timeout=settings.API_TIMEOUT * 2,  # Allow more time for tests
            user_id=user_id
        )
        
        # Log completion
        logger.info(
            "Testing complete", 
            playbook_id=req.playbook_id, 
            status=status, 
            log_size=len(logs)
        )
        
        # Schedule cleanup in background
        background_tasks.add_task(
            playbook_service.cleanup_molecule_artifacts, 
            req.playbook_id
        )
        
        return TestResponse(status=test_status, logs=logs)
        
    except PlaybookValidationError as e:
        logger.error("Playbook validation error", playbook_id=req.playbook_id, error=str(e))
        
        # Record telemetry for validation error
        if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
            database.record_telemetry(
                "test_validation_error",
                {"playbook_id": req.playbook_id, "error": str(e)},
                user_id=user_id
            )
            
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PlaybookExecutionError as e:
        if "timeout" in str(e).lower():
            logger.error("Testing timeout", playbook_id=req.playbook_id)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Testing process timed out"
            )
        else:
            logger.exception("Testing error", playbook_id=req.playbook_id, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Testing failed: {e}"
            )

@app.get(
    "/v1/schema",
    response_model=Dict[str, Any],
    dependencies=[Depends(role_required("generator"))],
    tags=["Schemas"],
    summary="Get module schema",
    description="Get the JSON schema for a specific Ansible module",
)
async def get_schema(
    module: str = Query(..., description="Module name"), 
    schemas: Dict[str, Any] = Depends(get_schema_store)
):
    """Get the JSON schema for a specific Ansible module."""
    logger.info("Schema request", module=module)
    
    key = module if module in schemas else module.replace("ansible.builtin.", "")
    if key not in schemas:
        logger.error("Schema not found", module=module)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Schema for module '{module}' not found"
        )
        
    return schemas[key]

@app.get(
    "/v1/history",
    response_model=List[Dict[str, Any]],
    dependencies=[Depends(role_required("generator"))],
    tags=["Playbooks"],
    summary="Get playbook history",
    description="Get playbook generation history, optionally filtered by domain",
)
async def get_history(domain: Optional[str] = Query(None, description="Filter by domain")):
    """Get playbook generation history (stub for future implementation)."""
    logger.info("History request", domain=domain)
    return []  # Stub for future history

@app.post(
    "/v1/feedback",
    dependencies=[Depends(role_required("tester"))],
    tags=["Feedback"],
    summary="Submit feedback",
    description="Record user feedback for a generated playbook",
)
async def post_feedback(
    request: Request,
    req: FeedbackRequest,
    playbook_service: PlaybookService = Depends(get_playbook_service),
):
    """Record user feedback for a generated playbook."""
    # Get user ID for feedback and telemetry
    user_id = get_user_id(request)
    
    logger.info(
        "Feedback received", 
        playbook_id=req.playbook_id, 
        rating=req.rating, 
        has_comment=req.comment is not None,
        user_id=user_id
    )
    
    try:
        # Validate playbook exists
        playbook_service._get_playbook_path(req.playbook_id)
        
        # Store feedback in database if enabled
        if settings.DB_ENABLED and settings.COLLECT_FEEDBACK:
            feedback_id = database.record_feedback(
                playbook_id=req.playbook_id,
                rating=req.rating,
                comment=req.comment,
                user_id=user_id
            )
            logger.info(f"Recorded feedback with ID {feedback_id}")
            
            # Record telemetry for feedback
            if settings.COLLECT_TELEMETRY:
                database.record_telemetry(
                    "feedback",
                    {
                        "playbook_id": req.playbook_id,
                        "rating": req.rating,
                        "has_comment": req.comment is not None,
                        "feedback_id": feedback_id
                    },
                    user_id=user_id
                )
        
        return {"status": "received", "stored": settings.DB_ENABLED and settings.COLLECT_FEEDBACK}
    
    except PlaybookValidationError as e:
        logger.error("Feedback validation error", playbook_id=req.playbook_id, error=str(e))
        
        # Record telemetry for validation error
        if settings.DB_ENABLED and settings.COLLECT_TELEMETRY:
            database.record_telemetry(
                "feedback_validation_error",
                {"playbook_id": req.playbook_id, "error": str(e)},
                user_id=user_id
            )
            
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

# Cache control endpoints
class CacheStatsResponse(BaseModel):
    """Response model for cache statistics."""
    schema_cache: Dict[str, Any]
    llm_cache: Dict[str, Any]
    playbook_cache: Dict[str, Any]
    total_entries: int

@app.get(
    "/api/admin/cache/stats",
    response_model=CacheStatsResponse,
    dependencies=[Depends(role_required("admin"))],
    tags=["Admin", "Cache"],
    summary="Get cache statistics",
    description="Get statistics about the caches",
)
async def get_cache_stats():
    """Get statistics about the caches."""
    schema_stats = schema_cache.stats()
    llm_stats = llm_cache.stats()
    playbook_stats = playbook_cache.stats()
    
    total = schema_stats["size"] + llm_stats["size"] + playbook_stats["size"]
    
    return CacheStatsResponse(
        schema_cache=schema_stats,
        llm_cache=llm_stats,
        playbook_cache=playbook_stats,
        total_entries=total
    )

@app.post(
    "/api/admin/cache/clear",
    dependencies=[Depends(role_required("admin"))],
    tags=["Admin", "Cache"],
    summary="Clear caches",
    description="Clear one or more caches",
)
async def clear_caches(
    schema: bool = Query(False, description="Clear schema cache"),
    llm: bool = Query(False, description="Clear LLM response cache"),
    playbook: bool = Query(False, description="Clear playbook cache"),
    all: bool = Query(False, description="Clear all caches"),
):
    """Clear one or more caches."""
    cleared = []
    
    if all or schema:
        schema_cache.clear()
        cleared.append("schema")
    
    if all or llm:
        llm_cache.clear()
        cleared.append("llm")
    
    if all or playbook:
        playbook_cache.clear()
        cleared.append("playbook")
    
    logger.info(f"Cleared caches: {', '.join(cleared)}")
    return {"status": "success", "cleared": cleared}

# Database management endpoints
class FeedbackStatsResponse(BaseModel):
    """Response model for feedback statistics."""
    total_feedback: int
    average_rating: float
    rating_counts: Dict[int, int]  # Rating -> count
    recent_feedback: List[Dict[str, Any]]

class TelemetryStatsResponse(BaseModel):
    """Response model for telemetry statistics."""
    total_events: int
    event_counts: Dict[str, int]  # Event type -> count
    recent_events: List[Dict[str, Any]]

class LLMUsageStatsResponse(BaseModel):
    """Response model for LLM usage statistics."""
    total_tokens: int
    total_requests: int
    providers: List[Dict[str, Any]]

# Task Models
class CreateTaskRequest(BaseModel):
    """Request model for creating a task."""
    task_type: str = Field(..., description="Type of task to create")

class TaskResponse(BaseModel):
    """Response model for task information."""
    task_id: str
    task_type: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: int
    details: Dict[str, Any]
    has_result: bool
    has_error: bool
    
class TaskListResponse(BaseModel):
    """Response model for task listing."""
    tasks: List[TaskResponse]
    
class TaskResultResponse(BaseModel):
    """Response model for task results."""
    task_id: str
    status: str
    result: Optional[Any] = None
    error: Optional[str] = None
    
class TaskSubmitRequest(BaseModel):
    """Request model for submitting a task for execution."""
    playbook_id: str = Field(..., description="ID of the playbook to operate on")
    
class AsyncPlaybookResponse(BaseModel):
    """Response model for asynchronous playbook operations."""
    task_id: str
    playbook_id: str
    status: str
    
# Monitoring Models
class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    components: Dict[str, Dict[str, Any]]
    meta: Dict[str, Any]
    
class ComponentHealthResponse(BaseModel):
    """Response model for component health check."""
    status: str
    details: Dict[str, Any]
    
class MetricsResponse(BaseModel):
    """Response model for metrics."""
    uptime_seconds: float
    requests_per_minute: float
    metrics: Dict[str, Any]
    system: Dict[str, Any]
    process: Dict[str, Any]
    
class SystemInfoResponse(BaseModel):
    """Response model for system information."""
    hostname: str
    platform: str
    python_version: str
    cpu_count: int
    cpu_model: str
    memory_total: int
    boot_time: str
    process_id: int
    process_start_time: str
    environment: str
    
class CSRFTokenResponse(BaseModel):
    """Response model for CSRF token."""
    token: str

@app.get(
    "/api/admin/stats/feedback",
    response_model=FeedbackStatsResponse,
    dependencies=[Depends(role_required("admin"))],
    tags=["Admin", "Stats"],
    summary="Get feedback statistics",
    description="Get statistics about user feedback",
)
async def get_feedback_stats():
    """Get statistics about user feedback."""
    if not settings.DB_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is disabled"
        )
    
    # Get recent feedback
    recent_feedback = database.get_feedback(limit=50)
    
    # Calculate statistics
    total_feedback = len(recent_feedback)
    if total_feedback == 0:
        average_rating = 0.0
        rating_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    else:
        ratings = [f["rating"] for f in recent_feedback]
        average_rating = sum(ratings) / len(ratings)
        
        # Count ratings
        rating_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for rating in ratings:
            rating_counts[rating] = rating_counts.get(rating, 0) + 1
    
    return FeedbackStatsResponse(
        total_feedback=total_feedback,
        average_rating=average_rating,
        rating_counts=rating_counts,
        recent_feedback=recent_feedback
    )

@app.get(
    "/api/admin/stats/telemetry",
    response_model=TelemetryStatsResponse,
    dependencies=[Depends(role_required("admin"))],
    tags=["Admin", "Stats"],
    summary="Get telemetry statistics",
    description="Get statistics about telemetry events",
)
async def get_telemetry_stats():
    """Get statistics about telemetry events."""
    if not settings.DB_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is disabled"
        )
    
    # Get recent events
    recent_events = database.get_telemetry(limit=100)
    
    # Calculate statistics
    total_events = len(recent_events)
    
    # Count event types
    event_counts = {}
    for event in recent_events:
        event_type = event["event_type"]
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    
    return TelemetryStatsResponse(
        total_events=total_events,
        event_counts=event_counts,
        recent_events=recent_events
    )

@app.get(
    "/api/admin/stats/llm",
    response_model=LLMUsageStatsResponse,
    dependencies=[Depends(role_required("admin"))],
    tags=["Admin", "Stats"],
    summary="Get LLM usage statistics",
    description="Get statistics about LLM usage",
)
async def get_llm_stats():
    """Get statistics about LLM usage."""
    if not settings.DB_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is disabled"
        )
    
    # Get usage stats from database
    usage_stats = database.get_llm_usage_stats()
    
    return LLMUsageStatsResponse(
        total_tokens=usage_stats["total_tokens"],
        total_requests=usage_stats["total_requests"],
        providers=usage_stats["providers"]
    )

# Health and monitoring endpoints
@app.get(
    "/health",
    response_model=HealthResponse,
)
async def health_check():
    """Get the health status of the application."""
    health_data = monitoring.HealthCheck.check_health()
    return health_data

@app.get(
    "/health/{component}",
    response_model=ComponentHealthResponse,
)
async def component_health_check(component: str):
    """Get the health status of a specific component."""
    if component not in [c.value for c in monitoring.Component]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component {component} not found"
        )
    
    health_method = getattr(monitoring.HealthCheck, f"check_{component}_health", None)
    if not health_method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Health check for component {component} not implemented"
        )
    
    health_data = health_method()
    return health_data

@app.get(
    "/metrics",
    response_model=MetricsResponse,
    dependencies=[Depends(role_required("admin"))],
)
async def get_application_metrics():
    """Get application metrics."""
    metrics = monitoring.get_metrics().get_metrics()
    return metrics

@app.get(
    "/system/info",
    response_model=SystemInfoResponse,
    dependencies=[Depends(role_required("admin"))],
)
async def get_system_info():
    """Get system information."""
    return monitoring.SystemInfo.get_system_info()
    
@app.get(
    "/v1/csrf-token",
    response_model=CSRFTokenResponse,
)
async def get_csrf_token(request: Request, response: Response):
    """Get a new CSRF token.
    
    This endpoint returns a new CSRF token and sets the corresponding cookie.
    The token must be included in the X-CSRF-Token header for all state-changing requests.
    """
    # Generate a new CSRF token
    token = secrets.token_urlsafe(32)
    
    # Set the CSRF cookie
    response.set_cookie(
        key="relia_csrf",
        value=token,
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite="lax",
        max_age=86400  # 24 hours
    )
    
    # Return the token in the response body
    return CSRFTokenResponse(token=token)

# Include dashboard router
if settings.MONITORING_ENABLED:
    from .dashboard.router import router as dashboard_router
    app.include_router(dashboard_router)
    
    # Mount static files
    dashboard_static_dir = Path(__file__).parent / "dashboard" / "static"
    if dashboard_static_dir.exists():
        app.mount("/dashboard/static", StaticFiles(directory=str(dashboard_static_dir)), name="dashboard_static")
    
# Task Endpoints
@app.get(
    "/v1/tasks",
    response_model=TaskListResponse,
    dependencies=[Depends(role_required("generator"))],
    tags=["Tasks"],
    summary="List tasks",
    description="List tasks for the current user",
)
async def list_tasks(
    request: Request,
    limit: int = Query(50, ge=1, le=100, description="Maximum number of tasks to return"),
):
    """List tasks for the current user."""
    user_id = get_user_id(request)
    task_list = tasks.list_tasks(user_id=user_id, limit=limit)
    
    return TaskListResponse(
        tasks=[TaskResponse(**task.to_dict()) for task in task_list]
    )

@app.get(
    "/v1/tasks/{task_id}",
    response_model=TaskResponse,
    dependencies=[Depends(role_required("generator"))],
    tags=["Tasks"],
    summary="Get task status",
    description="Get the status of a specific task",
)
async def get_task_status(task_id: str):
    """Get task status."""
    task = tasks.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    return TaskResponse(**task.to_dict())

@app.get(
    "/v1/tasks/{task_id}/result",
    response_model=TaskResultResponse,
    dependencies=[Depends(role_required("generator"))],
    tags=["Tasks"],
    summary="Get task result",
    description="Get the result of a completed task",
)
async def get_task_result(task_id: str):
    """Get task result."""
    task = tasks.get_task(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found"
        )
    
    if task.status not in (tasks.TaskStatus.COMPLETED, tasks.TaskStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task {task_id} is not complete (status: {task.status})"
        )
    
    return TaskResultResponse(
        task_id=task.task_id,
        status=task.status,
        result=task.result,
        error=task.error
    )

@app.post(
    "/v1/tasks/{task_id}/cancel",
    response_model=TaskResponse,
    dependencies=[Depends(role_required("generator"))],
    tags=["Tasks"],
    summary="Cancel task",
    description="Cancel a pending task",
)
async def cancel_task(task_id: str):
    """Cancel a pending task."""
    success = tasks.cancel_task(task_id)
    if not success:
        task = tasks.get_task(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel task {task_id} with status {task.status}"
            )
    
    task = tasks.get_task(task_id)
    return TaskResponse(**task.to_dict())

# Asynchronous variants of existing endpoints
@app.post(
    "/v1/async/lint",
    response_model=AsyncPlaybookResponse,
    dependencies=[Depends(role_required("tester"))],
    tags=["Async", "Playbooks"],
    summary="Lint playbook asynchronously",
    description="Lint a playbook in the background and return a task ID",
)
async def async_lint(
    request: Request,
    req: TaskSubmitRequest,
    playbook_service: PlaybookService = Depends(get_playbook_service),
):
    """Lint a playbook asynchronously."""
    user_id = get_user_id(request)
    
    # Create a task
    task = tasks.create_task("lint", user_id)
    
    # Store the playbook ID in the task details
    task.details["playbook_id"] = req.playbook_id
    
    # Submit the task for execution
    tasks.submit_task(
        task.task_id,
        playbook_service.lint_playbook,
        req.playbook_id,
        settings.API_TIMEOUT,
        user_id
    )
    
    return AsyncPlaybookResponse(
        task_id=task.task_id,
        playbook_id=req.playbook_id,
        status=task.status
    )

@app.post(
    "/v1/async/test",
    response_model=AsyncPlaybookResponse,
    dependencies=[Depends(role_required("tester"))],
    tags=["Async", "Playbooks"],
    summary="Test playbook asynchronously",
    description="Test a playbook in the background and return a task ID",
)
async def async_test(
    request: Request,
    req: TaskSubmitRequest,
    playbook_service: PlaybookService = Depends(get_playbook_service),
):
    """Test a playbook asynchronously."""
    user_id = get_user_id(request)
    
    # Create a task
    task = tasks.create_task("test", user_id)
    
    # Store the playbook ID in the task details
    task.details["playbook_id"] = req.playbook_id
    
    # Submit the task for execution
    tasks.submit_task(
        task.task_id,
        playbook_service.test_playbook,
        req.playbook_id,
        settings.API_TIMEOUT * 2,  # Allow more time for tests
        user_id
    )
    
    # Schedule cleanup in a background task
    # This will run after the test completes (inside the task)
    tasks.get_task_queue().executor.submit(
        playbook_service.cleanup_molecule_artifacts,
        req.playbook_id
    )
    
    return AsyncPlaybookResponse(
        task_id=task.task_id,
        playbook_id=req.playbook_id,
        status=task.status
    )
