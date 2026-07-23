---
inclusion: fileMatch
fileMatchPattern: '**/{*.py,requirements*.txt}'
---

# Python Virtual Environment & Dependencies

Standards for the Python virtual environment and requirements files.

> **Note:** This repo is packaged and distributed to end users, who run the `cli/` scripts to deploy infrastructure. End users do NOT develop or run tests, so test/dev packages must stay out of `cli/requirements.txt`.

## Virtual Environment

- Use `.ve` in the project root. If `.venv` or `venv` already exists, use that instead.
- Never commit it. `.gitignore` already excludes `.ve` and `.venv` (and the `.*` pattern).
- Use the latest available Python; do not pin the Python version.

```bash
python -m venv .ve            # create (only if none exists)
source .ve/bin/activate       # activate (Linux/macOS; Windows: .ve\Scripts\activate)
which python                  # verify it points into .ve
```

## Requirements Files

| File | Purpose | Shipped to end users |
|------|---------|----------------------|
| `cli/requirements.txt` | Runtime libs the `cli/` scripts import | Yes |
| `cli/requirements-test.txt` | Packages needed to run the test suite (local + CI/CD) | No |
| `cli/requirements-dev.txt` | Extra local-only maintainer tooling | No |

Rules:
- Keep `cli/requirements.txt` limited to what end-user scripts actually import.
- `requirements-test.txt` holds everything (beyond `requirements.txt`) needed to run tests automatically in CI.
- Start each layered file with an install-order comment.
- Prefer `>=` floors over exact pins; only pin to work around a specific issue, and comment it with a timeline to remove.
- Prune unused packages and keep versions current.

## Install Order

```bash
source .ve/bin/activate

# End users
pip install -r cli/requirements.txt

# Maintainers / CI (add on top of the line above)
pip install -r cli/requirements-test.txt
pip install -r cli/requirements-dev.txt   # local development only
```

## For AI Assistants

- Always activate the venv before running any Python or `pip` command; reuse an existing `.ve`/`.venv`/`venv` rather than creating a new one.
- Reference requirements files by their `cli/` path.
- When adding a Python package, record it in the correct layer (runtime → `requirements.txt`, test-only → `requirements-test.txt`, dev-only → `requirements-dev.txt`) instead of installing it ad hoc.
