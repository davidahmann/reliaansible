# Relia OSS
Relia OSS is a local-first, lightweight assistant for generating and validating Ansible playbooks on Linux, available as a CLI and VS Code extension.

## Features

- **Natural-Language → Valid Playbooks**: Generate Ansible YAML from plain English prompts.
- **Ansible Module Precision**: Inject live `ansible.builtin` schemas for parameter accuracy.
- **Built-In Validation**: Run `ansible-lint` and Molecule Docker scenarios locally.
- **Feedback Capture**: Thumbs-up/down and comments stored in SQLite for offline tuning.
- **Plugin Architecture**: Drop custom `{module}.json` files under `backend/plugins/`.
- **Extensible**: CLI (`relia-cli`) and an LSP-based VS Code extension with inline CodeLens commands.
- **Centralized Config**: Override defaults via `.env` or environment variables.
- **Monitoring & Health Checks**: Comprehensive monitoring for system health, metrics, and performance.
- **Asynchronous Tasks**: Background processing for long-running operations like testing.
- **Caching System**: Efficient caching of schemas, LLM responses, and playbooks.

### New Security & Production Features

- **HTTPS Enforcement**: Automatic HTTP-to-HTTPS redirection with HSTS headers.
- **Robust Authentication**: Secure JWT implementation with proper validation and refresh tokens.
- **CSRF Protection**: Double-submit cookie pattern for protecting against CSRF attacks.
- **Security Headers**: Comprehensive Content-Security-Policy and other security headers.
- **Path Traversal Protection**: Secure path validation to prevent directory traversal attacks.
- **Secrets Management**: Multi-backend secrets manager with support for environment, AWS, and Vault.
- **Database Connection Pooling**: Efficient database connections with proper transaction management.
- **Container Security**: Non-root user, proper permissions, and health checks.
- **Kubernetes Deployment**: Complete K8s manifests with horizontal scaling and security policies.

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- **Node.js 16+ & npm**
- **Docker** (required for Molecule scenarios)
- **Git**

### Clone the Repository

```bash
git clone git@github.com:davidahmann/relia.git
cd relia
```

### Configure Git (if needed)

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### Python & CLI Setup

```bash
# Optional: use Poetry
poetry install
# Or using virtualenv
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### VS Code Extension Setup

```bash
cd extension
npm install
npm run build
```

### DevContainer (Optional)

Open in VS Code and select **Remote-Containers: Reopen in Container** for a preconfigured environment.

---

## Configuration

Environment variables are loaded from a `.env` file in the repo root. Example:

```ini
# CLI & Backend
RELIA_BACKEND_URL=https://localhost:8000
RELIA_ENV=prod
RELIA_JWT_SECRET=supersecret
RELIA_CSRF_SECRET=anothersupersecret
RELIA_LLM=openai
RELIA_STALE_SCHEMA_DAYS=7

# Security settings
RELIA_ENFORCE_HTTPS=true
RELIA_SECURE_COOKIES=true
RELIA_HSTS_ENABLED=true
RELIA_HSTS_MAX_AGE=31536000

# Monitoring
RELIA_MONITORING_ENABLED=true
RELIA_HEALTH_CHECK_INTERVAL=60

# Secrets management (optional)
RELIA_SECRET_BACKEND=env  # Options: env, file, aws, vault
# AWS_SECRET_MANAGER=region (if using AWS secrets)
# VAULT_ADDR=https://vault:8200 (if using Vault)
# VAULT_TOKEN=vaultsecrettoken (if using Vault)

# Database (optional for PostgreSQL)
RELIA_DB_URL=postgresql://user:password@localhost:5432/relia
```

---

## Usage

### CLI

```bash
# View help
relia-cli --help

# Generate a playbook
relia-cli generate \
  --module ansible.builtin.lineinfile \
  --prompt "Ensure NTP is installed"

# Lint generated playbook
relia-cli lint <playbook_id>

# Run Molecule test
relia-cli test <playbook_id>

# Provide feedback
relia-cli feedback <playbook_id>

# Export feedback
relia-cli export-feedback feedback.csv

# Refresh schemas
relia-cli refresh-schemas lineinfile service

# Check schema staleness
relia-cli doctor

# Scaffold a starter playbook
relia-cli init-starter vm-bootstrap
```

Global verbose flag:
```bash
relia-cli --verbose generate --module ansible.builtin.service --prompt "Restart nginx"
```

### VS Code Extension

1. Open a `.yml` file.
2. Add a comment: `# relia: install nginx using lineinfile`.
3. Click the **Generate** CodeLens above the comment.
4. Use inline **Lint**, **Test**, and **Feedback** buttons.

---

## Monitoring and Health Checks

Relia includes a comprehensive monitoring system with a web dashboard and REST API endpoints:

### Web Dashboard

Access the monitoring dashboard at:
```
http://localhost:8000/dashboard
```

The dashboard provides:
- Health status monitoring for all components
- System resource usage metrics (CPU, memory, disk)
- Request statistics and performance metrics
- Comprehensive logging system with application, access, and telemetry logs
- Playbook management with viewing, linting, and testing tools
- Interactive charts for visualizing metrics and trends
- **Alert system** with configurable notifications for critical issues
- **Export functionality** for downloading logs and metrics in CSV/JSON formats
- **Dashboard customization** with themes, layouts, and auto-refresh options

### API Endpoints

```bash
# Check application health
curl http://localhost:8000/health

# Check specific component health
curl http://localhost:8000/health/database
curl http://localhost:8000/health/llm

# Get application metrics (admin role required)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/metrics

# Get system information (admin role required)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/system/info
```

---

## Directory Structure

```
.
├── backend/            # FastAPI backend
│   ├── dashboard/      # Admin dashboard UI
│   ├── services/       # Business logic services
│   ├── schemas/        # JSON schemas for Ansible modules
│   ├── plugins/        # Custom module plugins
│   └── security.py     # Security middlewares and utilities
├── kubernetes/         # Kubernetes deployment manifests
├── extension/          # VS Code extension (TypeScript)
├── relia_cli/          # CLI entrypoint (Python)
├── tests/              # Python unit tests
├── docs/               # Documentation
│   ├── architecture.md # System architecture
│   ├── security.md     # Security documentation
│   └── troubleshooting.md # Troubleshooting guide
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── IMPROVEMENTS.md     # List of implemented improvements
├── README.md
└── .github/
    └── workflows/      # CI/CD pipelines
```

---

## Testing

### Python Tests

```bash
# Run all tests
pytest

# Run with coverage
make coverage

# Generate HTML coverage report
make coverage-html

# Show coverage report from existing data
make coverage-report
```

### Extension E2E Tests

```bash
cd extension
npm test
```

### Docker Validation

```bash
# Build and test the Docker container
docker build -t relia:test .
docker run --rm -p 8000:8000 -e RELIA_ENV=test relia:test
```

### Kubernetes Testing (Local)

```bash
# Install kubectl and kind
kind create cluster --name relia-test

# Apply manifests
kubectl apply -k kubernetes/
```

---

## CI/CD

- **Lint & Tests**: runs on push/PR to `main` and manual dispatch (`.github/workflows/lint.yml`).
- **Demo**: verifies VS Code extension E2E (`demo.yml`).
- **Publish**: on pushing tags `v*.*.*`, publishes Python package to PyPI and VS Code extension to Marketplace (`publish.yml`).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## License

MIT © 2025 Relia