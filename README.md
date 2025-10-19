## Dorgy

<img src="images/dorgy.png" height="200">

`dorgy` is an AI-assisted command line toolkit that keeps growing collections of files tidy. The project already ships ingestion, classification, organization, watch, search, and undo workflows while we continue to flesh out the roadmap captured in `SPEC.md`.

### Why Dorgy?

- **Hands-off organization** – classify, rename, and relocate files using DSPy-backed language models plus fast heuristic fallbacks.
- **Continuous monitoring** – watch directories, batch changes, and export machine-readable summaries for downstream automation.
- **Rich undo and audit history** – track every operation in `.dorgy/` so reorganizations remain reversible.
- **Extensible foundation** – configuration is declarative, tests are automated via `uv`, and the roadmap is public.

---

## Installation

We are preparing the first PyPI release. Until the package lands on the index, install from source:

```bash
# Clone the repository
git clone https://github.com/bryaneburr/dorgie.git
cd dorgie

# Sync dependencies (includes dev extras)
uv sync

# Optional: install an editable build
uv pip install -e .
```

When the `dorgy` package is published to PyPI you will be able to install it directly:

```bash
# Using pip
pip install dorgy

# Using uv
uv pip install dorgy
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
- `processing` governs ingestion behaviour (batch sizes, captioning, concurrency, size limits). Enable `processing.process_images` to capture multimodal captions stored in `.dorgy/vision.json`.
- `organization` controls renaming and conflict strategies (append number, timestamp, skip) and timestamp preservation.
- `cli` toggles defaults for quiet/summary modes, Rich progress indicators, and move conflict handling (future releases will also surface search defaults).
- Watch services share the organization pipeline and respect `processing.watch.allow_deletions` unless `--allow-deletions` is passed.
- DSPy providers are configured through the `llm` block. Set `DORGY_USE_FALLBACK=1` to force the heuristic classifier during local testing.

---

## Release Workflow (In Flight)

1. Bump the version in `pyproject.toml`, commit outstanding changes, and run `uv run pre-commit run --all-files`.
2. Stage a TestPyPI dry run using a scoped token:
   ```bash
   export PYPI_TOKEN="pypi-AgEN..."
   uv publish --index-url https://test.pypi.org/legacy/ --token "$PYPI_TOKEN"
   ```
3. Validate the wheel from a clean virtual environment:
   ```bash
   uv pip install --index-url https://test.pypi.org/simple \
                  --extra-index-url https://pypi.org/simple dorgy==<version>
   dorgy --help
   ```
4. Publish to PyPI with the production token, tag the release (`git tag v<version>`), and update `SPEC.md` plus `notes/STATUS.md`.
5. Open a PR from `feature/release-prep` and merge after CI passes and the tag is confirmed.

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

- File issues and feature requests at [github.com/bryaneburr/dorgie/issues](https://github.com/bryaneburr/dorgie/issues).
- Join the discussion via GitHub Discussions (coming soon) or reach out through issues for contributor onboarding.
- If you build automations on top of `dorgy`, let us know—roadmap priorities are community driven.

---

## Authors

- **[Codex](openai.com/codex) (ChatGPT-5 based agent)** – primary implementation and tactical design across ingestion, classification, organization, and tooling.
- **Bryan E. Burr ([@bryaneburr](github.com/bryaneburr))** – supervisor, editor, and maintainer steering project direction and release planning.

---

## License

Released under the MIT License. See `LICENSE` for details.
