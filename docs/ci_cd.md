# Relia CI/CD Pipeline

This document explains the CI/CD pipeline for Relia OSS.

## Overview

The Relia CI/CD pipeline is designed to ensure code quality and provide a smooth release process for this local-first application. The pipeline includes:

1. Automated testing across multiple platforms
2. Type checking and linting
3. Docker container building
4. Automated release creation
5. Local development support

## GitHub Actions Workflow

Relia uses GitHub Actions for continuous integration and deployment. The workflow is defined in `.github/workflows/ci.yml`.

### Test Job

Tests the Python backend across multiple platforms and Python versions:

- **Operating Systems**: Ubuntu, macOS, Windows
- **Python Versions**: 3.10, 3.11
- **Steps**:
  - Install Python and Poetry
  - Install dependencies
  - Run linting with Ruff
  - Run tests with pytest

### TypeScript Job

Tests the VS Code extension across multiple platforms:

- **Operating Systems**: Ubuntu, macOS, Windows
- **Steps**:
  - Setup Node.js
  - Install dependencies
  - Run TypeScript type checking
  - Build the extension

### Docker Job

Builds a Docker image to ensure containerization works:

- **Runs On**: Ubuntu
- **Depends On**: Test and TypeScript jobs
- **Steps**:
  - Setup Docker Buildx
  - Build the Docker image

### Release Job

Creates GitHub releases automatically when tags are pushed:

- **Runs On**: Ubuntu
- **Triggers**: When a tag starting with 'v' is pushed
- **Depends On**: Test, TypeScript, and Docker jobs
- **Steps**:
  - Build Python package
  - Package VS Code extension
  - Extract changelog entry
  - Create GitHub release with artifacts

## Docker Support

The project includes a Dockerfile that defines a containerized environment for Relia. This is useful for:

1. Testing in a clean environment
2. Deploying to container platforms
3. Running in isolated mode

To build and run the Docker image:

```bash
# Build the image
docker build -t relia .

# Run the container
docker run -p 8000:8000 relia
```

## Local Development CI

For local development, a CI script is provided in `scripts/ci_checks.sh`. This script:

1. Verifies your development environment
2. Installs dependencies
3. Runs linting and tests
4. Builds TypeScript code (if applicable)
5. Tests Docker build (if Docker is available)

To use it:

```bash
./scripts/ci_checks.sh
```

## Release Process

The release process is automated through GitHub Actions:

1. Create and push a tag following semantic versioning: `git tag v1.0.0 && git push origin v1.0.0`
2. GitHub Actions will automatically:
   - Run all tests
   - Build Python package and VS Code extension
   - Create a GitHub Release with artifacts
   - Extract the corresponding entry from CHANGELOG.md

## CHANGELOG Format

For automatic changelog extraction to work, maintain the CHANGELOG.md in this format:

```markdown
# Changelog

## [1.0.0] - 2023-07-01

### Added
- New feature 1
- New feature 2

### Fixed
- Bug fix 1
- Bug fix 2

## [0.9.0] - 2023-06-01

... previous releases ...
```

## CI/CD Best Practices

1. **Always Run Local CI Before Pushing**: Run `./scripts/ci_checks.sh` before pushing changes
2. **Update CHANGELOG.md**: Add entries for all significant changes
3. **Follow Semantic Versioning**: Use MAJOR.MINOR.PATCH format for version numbers
4. **Write Good Tests**: Ensure your changes are covered by tests
5. **Keep Docker Images Minimal**: Avoid unnecessary dependencies in the Dockerfile