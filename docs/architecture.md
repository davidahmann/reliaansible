# Relia OSS Architecture

This document provides an overview of the Relia OSS architecture, component interactions, and deployment options.

## System Overview

Relia OSS is a web service that helps generate, validate, and manage Ansible playbooks. It consists of the following main components:

1. **Backend API Service** - FastAPI application providing the core functionality
2. **Database** - For storing playbooks, telemetry, and feedback
3. **LLM Integration** - Connects to OpenAI or Bedrock for playbook generation
4. **VS Code Extension** - Provides editor integration
5. **Caching Layer** - Performance optimization for frequently accessed data

## Component Architecture

### Backend Service

The backend service is built with FastAPI and follows a modular architecture:

- `app.py` - Main application entry point
- `config.py` - Configuration management
- `auth.py` - Authentication and authorization
- `security.py` - Security middleware and utilities
- `secrets.py` - Secrets management
- `database.py` - Database operations
- `llm_adapter.py` - LLM integration
- `cache.py` - Caching layer
- `monitoring.py` - Health checks and metrics
- `tasks.py` - Asynchronous task management
- `services/` - Business logic services
- `utils.py` - Utility functions
- `dashboard/` - Admin dashboard UI

### Component Interactions

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│                 │       │                 │       │                 │
│  VS Code        │◄─────►│  Backend API    │◄─────►│  LLM Service    │
│  Extension      │       │  Service        │       │  (OpenAI/AWS)   │
│                 │       │                 │       │                 │
└─────────────────┘       └────────┬────────┘       └─────────────────┘
                                   │
                                   │
                                   ▼
                          ┌─────────────────┐       ┌─────────────────┐
                          │                 │       │                 │
                          │  Database       │◄─────►│  Cache Layer    │
                          │                 │       │                 │
                          └─────────────────┘       └─────────────────┘
```

### Request Flow

1. **Authentication Flow**
   - Client sends request with JWT token
   - Backend validates token
   - RBAC determines access to resources

2. **Playbook Generation Flow**
   - Client sends generation request
   - Backend validates input
   - LLM adapter calls external API
   - Result is stored and returned

3. **Linting & Testing Flow**
   - Client submits playbook for validation
   - Backend executes ansible-lint/molecule
   - Results are returned to client

## Security Architecture

See [security.md](security.md) for detailed information on security features.

Key security aspects:
- HTTPS enforcement
- Authentication with JWT
- CSRF protection
- Input validation
- Secrets management
- Container security
- Rate limiting

## Database Architecture

The database schema has the following main tables:

1. **Playbooks** - Stores generated playbooks
   - ID (UUID)
   - User ID
   - Content
   - Module
   - Creation timestamp
   - Status

2. **Feedback** - User feedback on playbooks
   - ID
   - Playbook ID
   - Rating
   - Comments
   - Timestamp

3. **Telemetry** - Usage telemetry
   - ID
   - Event type
   - Details (JSON)
   - Timestamp
   - User ID

4. **LLM Usage** - Records of LLM API usage
   - ID
   - Provider
   - Tokens used
   - Cost
   - Timestamp

### Connection Pooling

Database connections are managed using SQLAlchemy with connection pooling:
- Min connections: 5
- Max connections: 20
- Timeout: 30s
- Overflow: 10

## Caching Architecture

The caching system has three main caches:

1. **Schema Cache** - Caches Ansible module schemas
2. **LLM Cache** - Caches LLM responses to reduce API calls
3. **Playbook Cache** - Caches generated playbooks and lint results

Cache invalidation strategies:
- TTL-based expiration (default: 1 hour)
- Size-based eviction (LRU policy)
- Manual purging via admin API

## Deployment Architecture

### Docker Deployment

For simple deployments, Docker Compose is provided:
- Backend service
- PostgreSQL database (optional)
- Redis cache (optional)

### Kubernetes Deployment

For production, Kubernetes manifests are provided:
- Deployment (2+ replicas)
- Service and Ingress
- Horizontal Pod Autoscaler
- Network Policies
- PersistentVolumeClaims

See the `kubernetes/` directory for detailed manifests.

### Scaling

The application is designed to scale horizontally:
- Stateless API service
- External database and cache
- Kubernetes HPA for auto-scaling

## Async Task Architecture

Background and long-running tasks are handled by a task system:

1. Task Creation - Tasks are created with a unique ID
2. Task Queue - Tasks are queued for execution
3. Worker Pool - Thread pool executes tasks
4. Status Tracking - Task status is tracked and retrievable
5. Result Storage - Task results are stored for later retrieval

Tasks supported:
- Playbook linting
- Playbook testing
- Database cleanup
- Cache maintenance

## Extension Architecture

The VS Code extension consists of:
- Extension main entry point
- CodeLens providers for YAML files
- Integration with backend API
- HTTPS and authentication support

## Configuration Management

Configuration is managed through:
1. Environment variables
2. .env files
3. Settings objects
4. Secrets management

Configuration priorities:
1. Secrets service
2. Environment variables
3. .env file
4. Default values

## Performance Considerations

The system is optimized for:
- Rapid API responses
- Efficient caching
- Connection pooling
- Rate limiting
- Resource limits

## Monitoring and Observability

The system provides:
- Health check endpoint (/health)
- Metrics endpoint (/metrics)
- Structured logging
- Request tracking
- Error monitoring

## Troubleshooting Guide

See [troubleshooting.md](troubleshooting.md) for detailed troubleshooting steps.

Common issues:
- Authentication problems
- Database connection issues
- LLM service integration
- Container deployment
- Cache performance