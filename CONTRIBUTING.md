# Contributing to Lyceum

Thanks for your interest in contributing to Lyceum. This document describes the workflow for reporting issues and submitting changes.

## Getting Started

1. Fork the repository and clone your fork.
2. Follow the [Quick Start](README.md#quick-start) in the README to get the app running locally.
3. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Branching Model

- `main` — stable branch; deployable at all times.
- `feature/*` — new features or enhancements.
- `fix/*` — bug fixes.
- `docs/*` — documentation-only changes.

## Commit Messages

Write commits in the imperative mood and keep the subject line under 72 characters.

```
Add CSV export for SWD requests

Adds a new /admin/export_requests route that streams a CSV response
filtered by the active date range. Uses the csv module and a generator
to avoid buffering the full result set in memory.
```

## Code Style

- **Python**: follow PEP 8. Prefer descriptive names over abbreviations.
- **SQL**: upper-case keywords (`SELECT`, `FROM`, `JOIN`), lower-case identifiers.
- **Templates**: keep logic in routes, not in Jinja.
- Do not commit secrets, `.env` files, or generated artifacts (`__pycache__`, `venv`).

## Testing Changes Locally

Before opening a PR:

- Run the app and smoke-test the affected flows (student / faculty / admin).
- Verify database migrations or schema edits against a fresh `schema.sql` apply.
- Confirm that the `.env.example` still documents every variable you read.

## Pull Requests

1. Push your branch and open a pull request against `main`.
2. Fill in the PR description with:
   - **What** the change does.
   - **Why** the change is needed.
   - **How** to test it (steps, screenshots for UI changes).
3. Link any related issues with `Closes #123`.
4. Keep PRs focused — one logical change per PR.

## Reporting Issues

When filing an issue, please include:

- Steps to reproduce.
- Expected vs. actual behavior.
- Environment (OS, Python version, MySQL version).
- Logs or stack traces (scrub any secrets first).

## Security

If you find a security vulnerability, **do not** open a public issue. Follow the private reporting process in [`SECURITY.md`](SECURITY.md). Operator-facing hardening guidance lives in the [Security Notes](README.md#security-notes) section of the README.

## License

By contributing, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
