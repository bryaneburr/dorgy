# Installation

Dorgy is distributed on PyPI and supports Python 3.11–3.12.

## PyPI (recommended)

```bash
# Using pip
pip install dorgy

# Using uv
uv pip install dorgy
```

## From source (contributors)

```bash
# Clone and enter the repo
git clone https://github.com/bryaneburr/dorgy.git
cd dorgy

# Install dependencies (dev extras)
uv sync --extra dev

# Optional: editable install
uv pip install -e .
```

See also: README Installation notes and the release workflow in docs/development/release.md.

