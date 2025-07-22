# Relia OSS Security Architecture

This document outlines the security architecture and best practices implemented in Relia OSS.

## Security Overview

Relia OSS is designed with security in mind, implementing multiple layers of protection:

1. **Transport Layer Security**
   - HTTPS enforcement and redirection
   - HTTP Strict Transport Security (HSTS)
   - TLS configuration following modern best practices

2. **Authentication & Authorization**
   - JWT token-based authentication
   - Role-based access control (RBAC)
   - Secure token handling with proper expiration

3. **Input Validation & Sanitization**
   - Path traversal protection
   - Strict input validation
   - Content validation

4. **Session Security**
   - CSRF protection
   - Secure cookie settings
   - Session management

5. **Container & Infrastructure Security**
   - Non-root user in containers
   - Principle of least privilege
   - Resource isolation
   - Health checks and monitoring

6. **Secrets Management**
   - Environment-specific secrets
   - External secrets providers (AWS, Vault)
   - Secure config handling

## HTTPS Configuration

Relia OSS enforces HTTPS in production environments using:

- HTTP-to-HTTPS redirection middleware
- HSTS headers with proper configuration
- Secure cookie attributes
- Content Security Policy headers

Configuration options in `config.py`:
```python
ENFORCE_HTTPS: bool = Field(True, validation_alias="RELIA_ENFORCE_HTTPS")
SECURE_COOKIES: bool = Field(True, validation_alias="RELIA_SECURE_COOKIES")
HSTS_ENABLED: bool = Field(True, validation_alias="RELIA_HSTS_ENABLED")
HSTS_MAX_AGE: int = Field(31536000, validation_alias="RELIA_HSTS_MAX_AGE")
```

## Authentication

Authentication is implemented using JWT (JSON Web Tokens) with several security features:

- Proper token expiration and validation
- Token refresh mechanism
- Strong cryptographic signatures
- Prevention of insecure development mode in production

Code examples:

```python
# Environment-based JWT configuration
# In production, requires a proper secret
if SECRET is None:
    if settings.ENV == "prod":
        logger.error("Authentication disabled in production mode! This is a critical security risk.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: JWT_SECRET must be set in production",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

## CSRF Protection

Cross-Site Request Forgery protection is implemented using:

- Double-submit cookie pattern
- CSRF tokens for state-changing operations
- Token validation on all mutating requests

Implementation details:
- `CSRFMiddleware` in `security.py`
- Token generation endpoint at `/v1/csrf-token`
- Cookie + header validation

## Input Validation

Input validation is implemented to prevent:

- Path traversal attacks
- SQL injection
- Command injection
- XSS attacks

Key components:
- Pydantic models for request validation
- Path validation utilities in `utils.py`
- Sanitization before database operations

## Secrets Management

The application supports multiple secret backends:

1. Environment variables (default)
2. .env files (for local development)
3. AWS Secrets Manager (for production)
4. HashiCorp Vault (for enterprise)

Configuration:
- Set `RELIA_SECRET_BACKEND` environment variable to select backend
- Secrets are accessed via the `get_secret()` function

## Container Security

The Docker container is configured with security best practices:

- Non-root user (`RELIA_UID=10001`)
- Minimal base image (Python slim)
- Principle of least privilege
- Read-only filesystem where possible
- Health checks
- Proper signal handling with tini

## Kubernetes Deployment Security

The Kubernetes deployment includes:

- Pod Security Context
- Network Policies
- Resource limits
- Horizontal Pod Autoscaler
- Secure Ingress configuration
- TLS termination
- Security headers

## Security Headers

The application sets the following security headers:

- Content-Security-Policy
- X-Content-Type-Options
- X-Frame-Options
- X-XSS-Protection
- Referrer-Policy
- Strict-Transport-Security

## Rate Limiting

Rate limiting protects against:

- Brute force attacks
- DoS attacks
- Excessive API usage

Implementation:
- IP-based rate limiting
- Path-specific rate limits
- Global rate limits

## Database Security

Database access is secured with:

- Connection pooling (via SQLAlchemy)
- Parameterized queries to prevent SQL injection
- Least privilege database users
- Validation before database operations

## Logging and Monitoring

Security events are logged and monitored:

- Structured logging for security events
- Authentication attempt logging
- Error and exception tracking
- Resource monitoring

## Security Recommendations

When deploying Relia OSS in production:

1. Always set strong secrets for JWT tokens
2. Enable HTTPS and HSTS
3. Use a secure database connection
4. Set up proper network security
5. Implement proper access controls
6. Regularly update dependencies
7. Monitor logs for security events

## Troubleshooting

Common security-related issues:

### HTTPS Issues
- Check SSL certificate configuration
- Verify HTTPS redirection middleware is enabled
- Check the `RELIA_ENFORCE_HTTPS` setting

### Authentication Issues
- Ensure `RELIA_JWT_SECRET` is properly set in production
- Check token expiration
- Verify client is sending the token correctly

### CSRF Issues
- Make sure your frontend includes the CSRF token in all state-changing requests
- Check that the token in the header matches the cookie
- Fetch a new token if errors persist

### Container Security Issues
- Ensure volume permissions are correctly set
- Check that the container has network access to required services
- Verify resource limits are appropriate