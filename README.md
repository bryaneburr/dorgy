[![CI](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml/badge.svg)](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml)
![PyPI - Version](https://img.shields.io/pypi/v/dorgy)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/dorgy)
![GitHub License](https://img.shields.io/github/license/bryaneburr/dorgy)

<img src="https://github.com/bryaneburr/dorgy/raw/main/images/dorgy_logo_white_transparent_background.png" alt="dorgy logo" height="200" style="height: 200px">

# Dorgy

AI‑assisted CLI to keep growing collections of files tidy. Organize folders with safe renames/moves and undo, watch directories for changes, and search collections with substring or semantic queries — all powered by portable per‑collection state.

## What It Does

Before (a messy folder):

```
my_docs/
  IMG_0234.jpg
  Scan_001.pdf
  taxes.txt
  contract_final_FINAL.docx
  notes (1).txt
  2023-05-07 14.23.10.png
  invoice.pdf
```

After (organized by category/date with safe renames, hyphenated lower‑case folders):

```
my_docs/
  .dorgy/                     # state, history, search index, logs
  documents/
    contracts/
      Employment Agreement (2023-06-15).pdf
    taxes/
      2023/
        Tax Notes.txt
  photos/
    2023/05/
      2023-05-07 14-23-10.png
  invoices/
    2023/
      ACME - April.pdf
```

Exact destinations depend on your config and prompts; all moves are reversible via `dorgy undo` using the state in `.dorgy`.

## Installation

### PyPI (recommended)

```bash
pip install dorgy
```

### From source (contributors)

```bash
git clone https://github.com/bryaneburr/dorgy.git
cd dorgy

# Optional: install dev dependencies
uv sync --extra dev

# Optional: editable install
uv pip install -e .
```

## Getting Started

```bash
# Inspect available commands
dorgy --help

# Organize a directory in place (dry run first)
dorgy org ./documents --dry-run
dorgy org ./documents

# Monitor a directory and emit JSON batches
dorgy watch ./inbox --json --once

# Undo the latest plan
dorgy undo ./documents --dry-run
dorgy status ./documents --json
```

See the docs for guides on Organize, Watch, Search, Move/Undo, and configuration details.

## Documentation

- Published site: https://bryaneburr.github.io/dorgy/
- Source: `docs/` (MkDocs + shadcn)
- Start with Getting Started → Quickstart and Configuration.

## Contributing

We welcome issues and pull requests. See `docs/development/contributing.md` for environment setup, pre‑commit hooks, and CI guidance.

### Local Workflow Helpers

Durango ships with [Invoke](https://www.pyinvoke.org/) tasks that wrap our `uv` commands. After installing dependencies, run:

```bash
uv run invoke --list
```

Common tasks include:

- `uv run invoke sync` — update the virtual environment (installs `dev` and `docs` extras by default).
- `uv run invoke ci` — replicate the CI pipeline locally (lint, mypy, tests, docs).
- `uv run invoke docs-serve` — launch the MkDocs server for live documentation previews.

## Authors

- Codex (ChatGPT‑5 based agent) — primary implementation and tactical design.
- Bryan E. Burr ([@bryaneburr](https://github.com/bryaneburr)) — supervisor, editor, and maintainer.

## License

Released under the MIT License. See `LICENSE` for details.
