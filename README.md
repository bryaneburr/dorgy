[![CI](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml/badge.svg)](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml)
![PyPI - Version](https://img.shields.io/pypi/v/dorgy)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/dorgy)
![GitHub License](https://img.shields.io/github/license/bryaneburr/dorgy)


## Dorgy

<img src="https://github.com/bryaneburr/dorgy/raw/main/images/dorgy_logo_white_transparent_background.png" alt="dorgy logo" height="200">

AI‑assisted CLI to keep growing collections of files tidy. Organize folders with safe renames/moves and undo, watch directories for changes, and search collections with substring or semantic queries — all powered by portable per‑collection state.

---

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

---

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

---

## Before → After (What Dorgy Does)

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

After (organized by category/date with safe renames):

```
my_docs/
  .dorgy/                     # state, history, search index, logs
  Documents/
    Contracts/
      Employment Agreement (2023-06-15).pdf
    Taxes/
      2023/
        Tax Notes.txt
  Photos/
    2023/05/
      2023-05-07 14-23-10.png
  Invoices/
    2023/
      ACME - April.pdf
```

Exact destinations depend on your config and prompts; all moves are reversible via `.dorgy/`.

---

## Documentation

- Published site: https://bryaneburr.github.io/dorgy/
- Source: `docs/` (MkDocs + shadcn)
- Start with Getting Started → Quickstart and Configuration.

## Contributing

We welcome issues and pull requests. See `docs/development/contributing.md` for environment setup, pre‑commit hooks, and CI guidance.

## Authors

- Codex (ChatGPT‑5 based agent) — primary implementation and tactical design.
- Bryan E. Burr ([@bryaneburr](https://github.com/bryaneburr)) — supervisor, editor, and maintainer.

## License

Released under the MIT License. See `LICENSE` for details.
