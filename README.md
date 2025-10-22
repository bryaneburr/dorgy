[![CI](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml/badge.svg)](https://github.com/bryaneburr/dorgy/actions/workflows/ci.yml)
![PyPI - Version](https://img.shields.io/pypi/v/dorgy)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/dorgy)
![PyPI - Status](https://img.shields.io/pypi/status/dorgy)
![GitHub License](https://img.shields.io/github/license/bryaneburr/dorgy)


## Dorgy

<img src="https://github.com/bryaneburr/dorgy/raw/main/images/dorgy.png" alt="dorgy logo" height="200">

`dorgy` is an AI-assisted command line toolkit that keeps growing collections of files tidy. The project already ships ingestion, classification, organization, watch, search, and undo workflows while we continue to flesh out the roadmap captured in `SPEC.md`. For a deeper dive into how the components fit together, see the [architecture overview](ARCH.md).

### Why Dorgy?

- **Hands-off organization** – classify, rename, and relocate files using DSPy-backed language models plus fast heuristic fallbacks.
- **Continuous monitoring** – watch directories, batch changes, and export machine-readable summaries for downstream automation.
- **Rich undo and audit history** – track every operation in `.dorgy/` so reorganizations remain reversible.
- **Extensible foundation** – configuration is declarative, tests are automated via `uv`, and the roadmap is public.

---

## Installation

### PyPI (recommended)

```bash
# Using pip
pip install dorgy

# Using uv
uv pip install dorgy
```

### From source

Clone the repository when you plan to contribute or work off the bleeding edge:

```bash
# Clone the repository
git clone https://github.com/bryaneburr/dorgy.git
cd dorgy

# Sync dependencies (includes dev extras)
uv sync

# Optional: install an editable build
uv pip install -e .
```

---

## Quickstart

```bash
# Inspect available commands
uv run dorgy --help

# Organize a directory in place (dry run first)
uv run dorgy org ./documents --dry-run
uv run dorgy org ./documents

# Monitor a directory and emit JSON batches
uv run dorgy watch ./inbox --json --once

# Undo the latest plan
uv run dorgy undo ./documents --dry-run
uv run dorgy status ./documents --json
```

---

## CLI Highlights

- **`dorgy org`** – batch ingest files, classify them, and apply structured moves with progress bars, summary/quiet toggles, and JSON payloads.
- **`dorgy watch`** – reuse the same pipeline in a long-running service; guard destructive deletions behind `--allow-deletions`.
- **`dorgy mv`** – move or rename tracked files while preserving state history.
- **`dorgy status` / `dorgy undo`** – inspect prior plans, audit history, and restore collections when needed.
- **Configuration commands** – `dorgy config view|set|edit` expose the full settings model.

All commands accept `--json` for machine-readable output and share standardized error payloads so automation can script around them.

---

## Configuration Essentials

- The primary config file lives at `~/.dorgy/config.yaml`; environment variables follow `DORGY__SECTION__KEY`.
- `processing` governs ingestion behaviour (batch sizes, captioning, concurrency, size limits). `processing.process_images` is enabled by default to capture multimodal captions stored in `.dorgy/vision.json`.
- `organization` controls renaming and conflict strategies (append number, timestamp, skip) and timestamp preservation. Automatic renaming is disabled by default (`organization.rename_files: false`) so classification runs remain non-destructive unless you opt in.
- `cli` toggles defaults for quiet/summary modes, Rich progress indicators, and move conflict handling (future releases will also surface search defaults).
- Watch services share the organization pipeline and respect `processing.watch.allow_deletions` unless `--allow-deletions` is passed.
- LLM models are configured through the `llm` block. The default target is `openai/gpt-5`; provide any LiteLLM-compatible identifier (for example `openai/gpt-4o-mini` or `openrouter/gpt-4o-mini:free`) via `llm.model`, supply `llm.api_key`/`llm.api_base_url` when required, and set `DORGY_USE_FALLBACKS=1` only when explicitly exercising heuristic classifiers in development.

### LLM Model Configuration

Configure language models through the `llm` block using `uv run dorgy config set llm.<field> <value>` or by editing `~/.dorgy/config.yaml`. Supply the exact LiteLLM/DSPy model string (``<provider>/<model>[:variant]``) via `llm.model`. The CLI also respects environment variables such as `DORGY__LLM__MODEL`, `DORGY__LLM__API_KEY`, and `DORGY__LLM__API_BASE_URL`.

Common configurations (substitute your own model identifiers and credentials as needed):

- **OpenAI**

  ```bash
  uv run dorgy config set llm.model openai/gpt-4o
  uv run dorgy config set llm.api_key "$OPENAI_API_KEY"
  ```

  YAML equivalent:

  ```yaml
  llm:
    model: openai/gpt-4o
    api_key: sk-...
  ```

- **Anthropic**

  ```bash
  uv run dorgy config set llm.model anthropic/claude-3-5-sonnet-20240620
  uv run dorgy config set llm.api_key "$ANTHROPIC_API_KEY"
  ```

- **xAI (Grok) via OpenRouter**

  ```bash
  uv run dorgy config set llm.model openrouter/grok-1
  uv run dorgy config set llm.api_key "$OPENROUTER_API_KEY"
  ```

- **Google Gemini**

  ```bash
  uv run dorgy config set llm.model google/gemini-1.5-pro
  uv run dorgy config set llm.api_key "$GOOGLE_API_KEY"
  ```

- **Local / Custom Gateway**

  ```bash
  uv run dorgy config set llm.model ollama/llama3
  uv run dorgy config set llm.api_base_url http://localhost:11434/v1
  ```

  When `llm.api_base_url` is set (e.g., Ollama, LM Studio, vLLM, or self-hosted gateways), `dorgy` sends requests directly to that endpoint and skips API-key enforcement.

---

## Automation & Release Tasks

We ship an Invoke task collection that wraps the `uv` toolchain so day-to-day automation stays consistent:

- `uv run invoke sync` – install dependencies (dev extras by default).
- `uv run invoke tests` / `uv run invoke lint` / `uv run invoke ci` – mirror the CI workflow locally.
- `uv run invoke release` – bump the version, commit `pyproject.toml`/`uv.lock`, rebuild artifacts, publish, and tag.
- `uv run invoke release --dry-run --push-tag` – preview the full release plan without modifying anything.
- `uv run invoke tag-version` – create (and optionally push) an annotated git tag.

### Release Workflow

1. Ensure the working tree is clean and CI passes locally:
   ```bash
   uv run invoke ci
   ```
2. Perform a dry run when validating credentials or reviewing the plan:
   ```bash
   uv run invoke release --dry-run --push-tag --token "$TEST_PYPI_TOKEN" \
       --index-url https://test.pypi.org/legacy/ --skip-existing
   ```
3. Publish to PyPI (commits the version bump, pushes the tag when requested):
   ```bash
   export PYPI_TOKEN="pypi-AgEN..."
   uv run invoke release --push-tag --token "$PYPI_TOKEN"
   ```
   Use `--index-url`/`--skip-existing` for TestPyPI dry runs, or `--tag-prefix ""` if you prefer unprefixed tags.
4. Update `SPEC.md`/`notes/STATUS.md` with release notes, open a PR from `feature/release-prep`, and merge once GitHub Actions succeeds.

---

## Roadmap

- `SPEC.md` tracks implementation phases and current status (Phase 9 – Distribution & Release Prep is underway; Phase 7 search/indexing work is queued next).
- `notes/STATUS.md` logs day-to-day progress, blockers, and next actions.
- Module-specific coordination details live in `src/dorgy/**/AGENTS.md`.

Upcoming milestones include vision-enriched classification refinements, enhanced CLI ergonomics, and expanded search/indexing APIs.

---

## Contributing

We welcome issues and pull requests while the project matures. A few guidelines keep things predictable:

- **Environment** – install dependencies with `uv sync` and run commands via `uv run ...`.
- **Pre-commit** – install hooks (`uv run pre-commit install`) and run `uv run pre-commit run --all-files` before pushing.
- **Branching** – create feature branches named `feature/<scope>` and keep them rebased until ready for review.
- **Testing** – the default pre-commit stack runs Ruff (lint/format/imports), MyPy, and `uv run pytest`.
- **Documentation** – follow Google-style docstrings and update relevant `AGENTS.md` files when adding automation-facing behaviours or integrations.
- **Coordination** – flag changes that impact the CLI contract, watch automation, or external integrations directly in the associated module `AGENTS.md`.

For release-specific work, use the branch/review workflow documented above and ensure TestPyPI validation is complete before tagging.

---

## Community & Support

- File issues and feature requests at [github.com/bryaneburr/dorgy/issues](https://github.com/bryaneburr/dorgy/issues).
- Join the discussion via GitHub Discussions (coming soon) or reach out through issues for contributor onboarding.
- If you build automations on top of `dorgy`, let us know—roadmap priorities are community driven.

---

## Authors

- **[Codex](https://openai.com/codex) (ChatGPT-5 based agent)** – primary implementation and tactical design across ingestion, classification, organization, and tooling.
- **Bryan E. Burr ([@bryaneburr](https://github.com/bryaneburr))** – supervisor, editor, and maintainer steering project direction and release planning.

---

## License

Released under the MIT License. See `LICENSE` for details.
