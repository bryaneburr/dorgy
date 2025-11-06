[![CI](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml/badge.svg)](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml)
![PyPI - Version](https://img.shields.io/pypi/v/dorgy)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/dorgy)
![GitHub License](https://img.shields.io/github/license/bryaneburr/dorgy)

# Dorgy

<img src="https://github.com/bryaneburr/dorgy/raw/main/images/dorgy_logo_cropped.png" alt="dorgy logo" height="150" style="height: 150px">

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

### Configuring LLM access

Set language model credentials and defaults via `dorgy config` commands or the YAML file at `~/.dorgy/config.yaml`. Important fields include:

- `llm.model` — full LiteLLM/DSPy model identifier (e.g., `openai/gpt-4o-mini`, `openrouter/gpt-4.1`).
- `llm.api_key` — API token for the selected provider (keep this in environment variables for security, e.g., `export DORGY__LLM__API_KEY=...`).
- `llm.api_base_url` — optional custom gateway URL (useful for openrouter, proxies, or self-hosted backends).
- `llm.temperature` / `llm.max_tokens` — sampling parameters that shape response creativity and length.

To override values temporarily, export environment variables following the `DORGY__SECTION__KEY` scheme—for example:

```bash
export DORGY__LLM__MODEL="openai/gpt-4o-mini"
export DORGY__LLM__API_KEY="sk-example"
export DORGY__LLM__API_BASE_URL="https://api.openai.com/v1"
```

Then run CLI commands as usual (`dorgy org`, `dorgy watch`, etc.).

### LLM Recommendations

We've tested `dorgy` with a number of LLMs and providers, and we've found the following to perform well:
- GPT-5
- Gemini 2.5
- If you use [OpenRouter](https://openrouter.ai), the `openrouter/auto` model is an interesting choice.

## Documentation

- Published site: https://bryaneburr.github.io/dorgy/
- Source: `docs/` (MkDocs + shadcn)
- Start with Getting Started → Quickstart and Configuration.
- Configuration management is powered by [Durango](https://github.com/bryaneburr/durango-config); see the Configuration guide for precedence details.


## Contributing

We welcome issues and pull requests. See `docs/development/contributing.md` for environment setup, pre‑commit hooks, and CI guidance.

### Local Workflow Helpers

This repository includes [Invoke](https://www.pyinvoke.org/) tasks that wrap our `uv` commands. After installing dependencies, run:

```bash
uv run invoke --list
```

Common tasks include:

- `uv run invoke sync` — update the virtual environment (installs `dev` and `docs` extras by default).
- `uv run invoke ci` — replicate the CI pipeline locally (lint, mypy, tests, docs).
- `uv run invoke docs-serve` — launch the MkDocs server for live documentation previews.

## License

Released under the MIT License. See `LICENSE` for details.
