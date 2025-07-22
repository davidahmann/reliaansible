# Relia OSS Troubleshooting Guide

This guide helps you diagnose and resolve common issues with Relia OSS.

## Table of Contents

1. [Authentication Issues](#authentication-issues)
2. [API Connection Problems](#api-connection-problems)
3. [Database Issues](#database-issues)
4. [Container Deployment Issues](#container-deployment-issues)
5. [Kubernetes Deployment Issues](#kubernetes-deployment-issues)
6. [LLM Integration Issues](#llm-integration-issues)
7. [Extension Issues](#extension-issues)
8. [Performance Problems](#performance-problems)
9. [Security Issues](#security-issues)
10. [Logging and Debugging](#logging-and-debugging)

## Authentication Issues

### JWT Token Problems

**Symptoms:**
- 401 Unauthorized responses
- "Invalid token" messages
- Token expiration issues

**Solutions:**
1. Check if `RELIA_JWT_SECRET` is properly set
   ```bash
   echo $RELIA_JWT_SECRET
   ```

2. Verify token format and expiration
   ```bash
   # Decode JWT token (replace YOUR_TOKEN)
   echo "YOUR_TOKEN" | cut -d"." -f2 | base64 -d | jq
   ```

3. Ensure client is sending token correctly
   - Header format: `Authorization: Bearer YOUR_TOKEN`

4. In development, ensure environment is set correctly
   ```bash
   export RELIA_ENV=dev
   ```

### Role-Based Access Issues

**Symptoms:**
- 403 Forbidden responses
- "Insufficient permissions" messages

**Solutions:**
1. Check user roles in token payload
2. Ensure required roles are assigned
3. Verify role_required dependency is correctly applied to endpoints

## API Connection Problems

### CORS Issues

**Symptoms:**
- Browser console CORS errors
- Failed preflight requests

**Solutions:**
1. Check allowed origins configuration
   ```python
   # In app.py
   allowed_origins = os.getenv(
       "RELIA_CORS_ORIGINS", 
       "http://localhost:8000,http://localhost:3000"
   ).split(",")
   ```

2. Ensure your frontend origin is in the allowed list
   ```bash
   export RELIA_CORS_ORIGINS="https://yourdomain.com,http://localhost:3000"
   ```

### HTTPS/TLS Issues

**Symptoms:**
- TLS handshake failures
- Mixed content warnings
- Redirect loops

**Solutions:**
1. Check certificate configuration
2. Verify HTTPS settings
   ```bash
   export RELIA_ENFORCE_HTTPS=true
   export RELIA_SECURE_COOKIES=true
   export RELIA_HSTS_ENABLED=true
   ```
3. For local development, disable HTTPS enforcement
   ```bash
   export RELIA_ENFORCE_HTTPS=false
   ```

## Database Issues

### Connection Problems

**Symptoms:**
- Database connection errors
- "Failed to initialize database" messages

**Solutions:**
1. Check database connectivity
   ```bash
   nc -zv database-host 5432
   ```

2. Verify database credentials
   ```bash
   # Check if credentials are properly set
   echo $RELIA_DB_USER
   echo $RELIA_DB_PASSWORD
   ```

3. Ensure database exists and user has proper permissions

### Connection Pool Exhaustion

**Symptoms:**
- "Too many connections" errors
- Slow response times under load

**Solutions:**
1. Check current connection usage
   ```sql
   SELECT count(*) FROM pg_stat_activity;
   ```

2. Adjust connection pool settings
   ```python
   # In database.py
   engine = create_engine(
       connection_string,
       pool_size=10,           # Increase for more connections
       max_overflow=20,        # Increase for more temporary connections
       pool_timeout=30,        # Timeout for getting a connection from pool
       pool_recycle=1800       # Connection recycle time (seconds)
   )
   ```

## Container Deployment Issues

### Container Startup Failures

**Symptoms:**
- Container exits immediately
- Health check failures

**Solutions:**
1. Check container logs
   ```bash
   docker logs relia-backend
   ```

2. Verify environment variables are set
   ```bash
   docker inspect relia-backend | grep -A 20 "Env"
   ```

3. Check user permissions
   ```bash
   # Ensure volumes have correct permissions
   sudo chown -R 10001:10001 .relia-data
   sudo chown -R 10001:10001 .relia-playbooks
   ```

### Volume Mounting Issues

**Symptoms:**
- "Permission denied" errors
- Missing data between restarts

**Solutions:**
1. Check volume mounts
   ```bash
   docker inspect -f '{{ .Mounts }}' relia-backend
   ```

2. Verify directory ownership and permissions
   ```bash
   ls -la .relia-data
   ls -la .relia-playbooks
   ```

## Kubernetes Deployment Issues

### Pod Startup Issues

**Symptoms:**
- Pods stuck in Pending state
- CrashLoopBackOff status
- Failed health checks

**Solutions:**
1. Check pod status and events
   ```bash
   kubectl describe pod -l app=relia
   ```

2. View pod logs
   ```bash
   kubectl logs -l app=relia -c backend
   ```

3. Verify secrets are properly created
   ```bash
   kubectl get secrets relia-secrets
   ```

### Ingress/Networking Issues

**Symptoms:**
- Service unavailable
- 404 or 503 errors

**Solutions:**
1. Check service status
   ```bash
   kubectl get service relia-backend
   ```

2. Verify ingress configuration
   ```bash
   kubectl describe ingress relia-ingress
   ```

3. Check network policies
   ```bash
   kubectl describe networkpolicy relia-backend-network-policy
   ```

## LLM Integration Issues

### API Connection Failures

**Symptoms:**
- "LLM service error" messages
- Timeout errors on generation

**Solutions:**
1. Check API key and credentials
   ```bash
   echo $OPENAI_API_KEY
   ```

2. Verify LLM provider configuration
   ```bash
   export RELIA_LLM=openai  # or 'bedrock'
   ```

3. Test API connectivity
   ```bash
   curl -I https://api.openai.com
   ```

### Rate Limiting or Quota Issues

**Symptoms:**
- 429 Too Many Requests errors
- "Quota exceeded" messages

**Solutions:**
1. Implement backoff and retry logic
2. Check usage limits in provider dashboard
3. Consider upgrading service tier or implementing request batching

## Extension Issues

### Connection Problems

**Symptoms:**
- "API call failed" messages
- Extension commands not working

**Solutions:**
1. Check extension settings
   - API base URL configuration
   - Authentication token

2. Verify backend is accessible
   ```bash
   curl -I https://your-api-url/health
   ```

3. Check CORS settings for extension origin

### Certificate Issues

**Symptoms:**
- TLS certificate validation errors
- "Self-signed certificate" warnings

**Solutions:**
1. For development, enable the "Allow Self-Signed Certificates" option in extension settings
2. In production, ensure proper TLS certificates are installed
3. Check extension HTTPS agent configuration

## Performance Problems

### Slow Response Times

**Symptoms:**
- API requests taking too long
- Timeout errors

**Solutions:**
1. Enable and check caching
   ```python
   # Check cache stats
   curl http://localhost:8000/api/admin/cache/stats
   ```

2. Optimize database queries
   - Add indexes for frequently queried fields
   - Optimize JOIN operations

3. Profile application
   ```bash
   PYTHONPROFILEIO=1 uvicorn backend.app:app
   ```

### Memory Usage Issues

**Symptoms:**
- High memory consumption
- Out of memory errors

**Solutions:**
1. Check memory usage
   ```bash
   docker stats relia-backend
   ```

2. Adjust resource limits
   - In docker-compose.yml or kubernetes manifests

3. Look for memory leaks
   - Monitor memory usage over time
   - Check for unbounded caches or collections

## Security Issues

### CSRF Errors

**Symptoms:**
- 403 Forbidden on POST/PUT/DELETE requests
- "CSRF token missing or invalid" messages

**Solutions:**
1. Ensure client fetches CSRF token
   ```javascript
   const response = await fetch('/v1/csrf-token');
   const { token } = await response.json();
   ```

2. Include token in headers
   ```javascript
   headers: {
     'Content-Type': 'application/json',
     'X-CSRF-Token': token
   }
   ```

### Rate Limit Exceeded

**Symptoms:**
- 429 Too Many Requests errors
- "Rate limit exceeded" messages

**Solutions:**
1. Implement client-side rate limiting
2. Batch requests where possible
3. Check for unintended request loops

## Logging and Debugging

### Enabling Debug Logs

```bash
# Set log level to DEBUG
export LOG_LEVEL=DEBUG
```

### Structured Logging

The application uses structured logging with JSON format. To parse logs:

```bash
# Extract ERROR level logs
docker logs relia-backend | grep '"level":"ERROR"' | jq

# Extract specific component logs
docker logs relia-backend | grep '"component":"auth"' | jq
```

### Health Check and Metrics

```bash
# Get health status
curl http://localhost:8000/health

# Get component health
curl http://localhost:8000/health/database

# Get metrics
curl http://localhost:8000/metrics
```

## Getting Additional Help

If you're still experiencing issues:

1. Check the [GitHub Issues](https://github.com/your-org/relia-oss/issues)
2. Search for similar problems in closed issues
3. Open a new issue with:
   - Detailed description of the problem
   - Steps to reproduce
   - Environment details (OS, container version, etc.)
   - Relevant logs or error messages