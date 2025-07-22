# Contributing to Relia OSS

First off, thanks for taking the time to improve Relia OSS! We welcome all contributions—be it bug reports, new features, documentation tweaks, or community support. By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone** your fork:
   ```bash
   git clone git@github.com:davidahmann/relia.git
   cd relia-oss
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b feature/my-cool-feature
   ```
4. **Install dependencies**:
   - Python & CLI:
     ```bash
     poetry install    # or venv + pip install -e .
     ```
   - Extension:
     ```bash
     cd extension && npm install
     ```
5. **Make your changes.** Follow the coding standards below.
6. **Add tests** covering new behavior:
   - Python tests under `tests/` with pytest.
   - Extension tests under `extension/tests/` with ts-node and @vscode/test-electron.
7. **Run the test suite**:
   ```bash
   # From repo root
   pytest

   # In extension/
   npm test
   ```
8. **Commit and push**:
   ```bash
   git add .
   git commit -m "feat: describe your change"
   git push origin feature/my-cool-feature
   ```
9. **Open a Pull Request** against `main`. Use the PR template and link any related issues.

## Branch & PR Workflow

- Target branch: `main` (short-lived feature branches).
- PR titles: `<type>(<scope>): <short description>` (e.g. `fix(cli): handle network timeouts`).
- Describe _why_ the change is needed, not just _what_ changed.
- After review, squash-merge with a descriptive commit message.

## Plugin & Schema Contributions

Relia OSS supports drop-in plugins for custom Ansible schemas:
1. Add your `{module_name}.json` file under `backend/plugins/`.
2. Ensure it adheres to the existing schema structure (see `backend/schemas/`).
3. Include a Molecule scenario under `starter/` if your plugin requires testing.
4. Update docs or add a new sample in `starter/`.

## Coding Standards

- **Python**:
  - Follow PEP8. Use `black .` and `ruff .` before committing.
- **TypeScript**:
  - Follow our `tsconfig.json` and ESLint rules. Run `npm run build`.
- **Markdown**:
  - Wrap lines at ~80 characters. Use headings and lists to structure content.

## Reporting Issues

Please use the issue templates in `.github/ISSUE_TEMPLATE/`:
- **Bug report**: fill in reproduction steps and expected vs actual behavior.
- **Feature request**: describe the use case and why it matters.

## Community & Support

- Join GitHub Discussions for general Q&A.
- For private or enterprise support, contact your vendor or consul.

## Thank You

Your contributions make Relia OSS better for everyone. We appreciate your help! You rock. 🎉

