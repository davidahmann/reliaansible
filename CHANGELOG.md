# Changelog

All notable changes to **Relia OSS** will be documented in this file.
This project adheres to [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
- Prepare for next improvements and bug fixes.
- Placeholder for upcoming minor and patch releases.

## [1.0.0] - 2025-04-22
### Added
- **Core Architecture**: FastAPI backend with endpoints for `/generate`, `/lint`, `/test`, `/schema`, `/history`, and `/feedback` (stubbed)  
- **CLI**: `relia-cli` with commands: `generate`, `lint`, `test`, `feedback`, `export-feedback`, `refresh-schemas`, `doctor`, `init-starter`, and `telemetry`  
- **VS Code Extension**: LSP‑based CodeLens provider for inline `# relia:` directives, plus generate/lint/test/feedback commands  
- **Schema Harvesting**: Local schema sync for `ansible.builtin` modules with plugin overlay support  
- **Validation & Testing**: `ansible-lint` integration and Molecule Docker scenarios  
- **Feedback Capture**: Local SQLite storage for thumbs‑up/down and comments; telemetry module for opt‑in event logging  
- **Configuration**: Centralized settings via Pydantic (`backend/config.py`, `relia_cli/config.py`) with `.env` support  
- **Observability**: Global `--verbose` flag in CLI; structured logging in backend  
- **Testing**:  
  - Python unit tests for plugin loader, backend endpoints, and CLI help/verbose flag  
  - TS‑based E2E tests for VS Code extension using `@vscode/test-electron`  
- **Documentation**:  
  - `README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`  
  - Initial `CHANGELOG.md`  
- **CI/CD**: GitHub Actions workflows for linting, testing, demo, and publishing to PyPI & VS Code Marketplace

### Changed
- Refactored code to remove hard‑coded paths and magic constants; use centralized config classes  
- Updated TypeScript config to include both `src/` and `tests/` directories; resolved LSP import issues  
- Merged plugin loader and base schemas for custom module definitions  
- Improved logging formats and exit codes across CLI and backend

### Fixed
- Resolved missing import errors (`fastapi.security`, `vscode`, `vscode-languageserver`)  
- Corrected `languageServer.ts` signatures for `TextDocuments` and connection creation  
- Ensured all paths and settings are referenced from Pydantic settings objects  
- Addressed CI test path issues by relocating the extension E2E test into `extension/tests/`  

### Removed
- Deprecated `vscode-test` dependency; replaced with `@vscode/test-electron`  
- Removed global `rootDir` misconfiguration in `tsconfig.json` causing test exclusion  

### Security
- Added `Code of Conduct` and `Contributing` guidelines  
- Ensured no secrets are committed; provided `.env` pattern and `.gitignore` recommendations

