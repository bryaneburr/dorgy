# Continuous Integration

GitHub Actions enforces formatting, linting, type checks, and tests using `uv`.

Workflow: `.github/workflows/ci.yml`

- Ruff lint and format checks
- MyPy: `uv run mypy src main.py`
- Pytest: `uv run pytest`

Docs are validated and deployed via the GitHub Pages workflow:

- On pull requests: the Pages workflow builds the MkDocs site (no deploy) to catch errors early.
- On pushes to main: the same workflow builds and deploys to GitHub Pages.

Local validation:

```bash
uv sync --extra docs
uv run mkdocs build --strict
```
