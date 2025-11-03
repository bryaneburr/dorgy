# Release & Distribution

Automation uses Invoke tasks that wrap `uv`.

Common workflows:

```bash
# CI parity
uv run invoke ci

# Dry-run a release to TestPyPI
uv run invoke release --dry-run --push-tag --token "$TEST_PYPI_TOKEN" \
    --index-url https://test.pypi.org/legacy/ --skip-existing

# Publish to PyPI
export PYPI_TOKEN="pypi-..."
uv run invoke release --push-tag --token "$PYPI_TOKEN"
```

Update `SPEC.md` (Phase 9) and `notes/STATUS.md` after releases. Use a feature branch and ensure CI is green before merging to main.

