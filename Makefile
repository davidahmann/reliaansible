# Makefile for Relia OSS

.PHONY: install lint test coverage coverage-html coverage-report demo demo-check extension-test test-all smoke-install clean

## Install all dependencies
install:
	poetry install --no-interaction --no-root
	cd extension && npm ci

## Lint Python & Ansible code
lint:
	poetry run ruff check .
	poetry run ansible-lint backend/ relia_cli/

## Run tests only
test:
	poetry run pytest

## Run pytest with coverage
coverage:
	poetry run pytest --cov=backend --cov=relia_cli --cov-report=xml

## Run pytest with HTML coverage report
coverage-html:
	poetry run pytest --cov=backend --cov=relia_cli --cov-report=html

## Generate coverage report from existing data
coverage-report:
	poetry run coverage report

## Build & test VS Code extension only
extension-test:
	@echo "Building & testing VS Code extension..."
	cd extension && npm ci && npm test

## Start the demo sandbox (FastAPI via Uvicorn)
demo:
	@echo "Starting demo sandbox (FastAPI via Uvicorn)..."
	poetry run uvicorn backend.app:app --host 0.0.0.0 --port 8000 &

## CI entrypoint for API and extension testing
demo-check:
	@echo "Setting up data directory..."
	@mkdir -p .relia-data
	@chmod -R 777 .relia-data
	@mkdir -p .relia-playbooks
	@chmod -R 777 .relia-playbooks
	@echo "Configuring database..."
	@RELIA_COLLECT_TELEMETRY=false RELIA_DB_ENABLED=false RELIA_COLLECT_FEEDBACK=false uvicorn backend.app:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 & \
	PID=$$!; \
	echo "Waiting for backend to be ready..."; \
	for i in 1 2 3 4 5; do \
		if curl -s http://localhost:8000/api/openapi.json | grep -q '"openapi"'; then \
			echo "✔ API health check passed"; \
			break; \
		else \
			echo "Attempt $$i failed, retrying in 3s..."; \
			sleep 3; \
		fi; \
	done; \
	echo "Final check of /api/openapi.json"; \
	if ! curl -s http://localhost:8000/api/openapi.json | grep -q '"openapi"'; then \
		echo "✖ API health check failed"; exit 1; \
	fi

	@echo "Building & testing VS Code extension..."
	cd extension && npm ci && npm test

## Composite test target with coverage
test-all: install lint coverage extension-test

## Smoke-test pip install in a fresh virtualenv
smoke-install:
	@echo "Testing local install in clean venv..."
	python -m venv .venv-smoke
	.venv-smoke/bin/pip install --upgrade pip
	.venv-smoke/bin/pip install .
	.venv-smoke/bin/relia-cli --help > /dev/null
	@echo "✔ Smoke install passed"

## Clean up background services and build artifacts
clean:
	@echo "Cleaning up background services and artifacts..."
	pkill -f "uvicorn backend.app:app" || true
	rm -rf .venv-smoke .pytest_cache dist/ coverage.xml .relia-playbooks .relia-data

