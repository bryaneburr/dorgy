# Status Log

## 2025-10-14
- Initialized tracking scheme; updated `SPEC.md` implementation phases and expanded coordination directives in `AGENTS.md`.
- Added this status log to capture ongoing progress, blockers, and next steps.
- Created feature branch `feature/phase-0-foundations` and confirmed `uv` tooling availability (`uv --version`, `uv run python -V`).
- Scaffolded package structure in `src/dorgy`, introduced Click-based CLI skeleton, and wired console entry point along with `python -m dorgy`.
- Updated `pyproject.toml` for package metadata, dependencies, `uv` management, and console script; regenerated `uv.lock`.
- Added baseline README guidance and marked Phase 0 status as in progress within `SPEC.md`.
- Standardized local Python to 3.11 by updating `.python-version`, so uv commands automatically use the compatible interpreter.
- Established pre-commit configuration (Ruff lint/format/imports, MyPy, `uv run pytest`), added tool configs in `pyproject.toml`, and documented workflow updates in README/AGENTS.
- Added scaffolding for configuration and state management modules (placeholders plus Pydantic models) with accompanying tests to keep future implementations guided.
- Documented Phase 1 scope and added resolver placeholders outlining precedence (CLI > env > file > defaults) along with tests asserting the current NotImplemented status.
- Next actions: outline CLI command behaviors for Phase 1, design the config load/save workflow ahead of implementation, and capture ingestion pipeline assumptions in SPEC.md.

## 2025-10-15
- Merged Phase 0 foundations into `main` and created `feature/phase-1-config` for the next stage of work.
- Updated `SPEC.md` to mark Phase 0 complete and Phase 1 in progress; captured ingestion pipeline assumptions.
- Implemented configuration persistence/resolution (file/env/CLI precedence), wired `dorgy config view|set|edit`, and added unit/CLI tests.
- Documented configuration usage in README/AGENTS to guide future contributors.
- Delivered state repository persistence helpers (`state.json`, `orig.json`, review/quarantine folders) with tests covering round-trips and error handling.
- Phase 1 complete; SPEC table updated accordingly. Upcoming focus: integrate configuration/state usage into future commands and begin Phase 2 ingestion scaffolding.

## 2025-10-16
- Created `feature/phase-2-ingestion` branch and expanded SPEC with detailed ingestion architecture goals/deliverables.
- Next actions: scaffold ingestion modules (`discovery`, `detectors`, `extractors`, `pipeline`), introduce Pydantic models for descriptors, and add placeholder tests.
- Wired ingestion pipeline into `dorgy org`, expanded metadata extraction for text/images/json, added CLI/state tests, and documented Phase 3 plan in SPEC.
- Upcoming focus: integrate classification pipeline (Phase 3) atop the ingestion outputs and enhance error handling/quarantine flows.
- Implemented locked-file copy/wait policies, oversized sampling, quarantine moves, and ingestion logging to `dorgy.log`; added tests covering these behaviours.

## 2025-10-17
- Started Phase 3 on `feature/phase-3-classification`; added classification models, DSPy engine scaffolding, and smoke tests obeying Google-style docstrings.
- Next actions: implement DSPy-backed classification, persist decisions into state, and extend CLI workflows to surface classification results.
- Implemented heuristic classification fallback, CLI integration (including rename toggle support), state persistence of decisions, and coverage for new behaviours.
- Added JSON-backed classification cache, confidence-based review routing, and optional DSPy fallback toggle via `DORGY_USE_FALLBACK`.

## 2025-10-18
- Began Phase 4 organization engine: planner/executor scaffolding, rename conflict resolution, category-based moves, and undo/logging (`last_plan.json`).
- CLI `org` now previews/applies rename+move operations and logs details to `.dorgy/dorgy.log`.

## 2025-10-16 (cont.)
- Replaced all Python module/class/function docstrings with Google-style format across src/ and tests/ to standardize documentation quality.
- Updated `AGENTS.md` directives to mandate Google-style docstrings for future contributions.
- Ran `uv run pre-commit run --all-files` to validate formatting, linting, and tests prior to push.
- Next actions: audit SPEC.md for any docstring-related expectations that should be surfaced in upcoming phases.

## 2025-10-19
- Extended the organization planner to honour `organization.conflict_resolution` (append_number, timestamp, skip) with timestamp injection for tests and surfaced `plan.notes` through the CLI.
- Added timestamp/skip collision coverage to `tests/test_organization_scaffolding.py`, updated SPEC and organization AGENTS guidance, and confirmed behaviour via `uv run pytest`.
- Observed test suite summary: 37 passed, 1 skipped (DSPy optional dependency).
- Next actions: wire history playback into undo/status commands and outline transactional staging requirements before expanding to watch/mv integration for Phase 5.
- Persisted rename/move history events to `.dorgy/history.jsonl`, exposed `OperationEvent` models, and wired `StateRepository.append_history` with executor-generated records. Updated state tests/docs accordingly and re-ran `uv run pytest` (38 passed, 1 skipped) to verify the new logging.
- Captured ingestion snapshots into `.dorgy/orig.json` before organization runs, exposed them through `dorgy undo --dry-run`, and expanded CLI/state tests to cover the snapshot schema.
- Introduced staged execution for organization plans so renames/moves occur from `.dorgy/staging/<session>` with automatic rollback on failure; added regression tests covering successful runs and conflict restoration, then re-ran `uv run pytest` (40 passed, 1 skipped).
- Surfaced recent `.dorgy/history.jsonl` entries during `dorgy undo --dry-run`, added repository helpers for reading history, and verified the output/limit logic with dedicated tests (41 passed, 1 skipped).
- Implemented `dorgy org --output PATH` relocation by copying organized files into the target directory, preserving originals and persisting state/history under the destination `.dorgy`; updated CLI/executor to support copy-mode staging and added integration coverage.
- Added `dorgy undo --json` for machine-readable rollback previews/results, serialising plans, snapshots, and recent history; expanded CLI tests to assert JSON payload shape (43 passed, 1 skipped).
- Introduced `dorgy status` for read-only collection summaries (text/JSON) leveraging state, history, and snapshot metadata; documented the command and validated output via new CLI tests (46 passed, 1 skipped).

## 2025-10-20
- Delivered Phase 4.5 CLI polish: shared summary helpers, `--summary/--quiet` toggles, standardised JSON error payloads, and executed `dorgy org --json` parity covering plan/state/history details.
- Added a `cli` configuration block (quiet/summary defaults, status history limit), refreshed README/SPEC guidance, and expanded tests for precedence plus new summary/quiet behaviours.
- Extended CLI integration coverage for JSON error responses and quiet defaults; `uv run pytest` now reports 51 passed, 1 skipped.
- Next actions: begin Phase 5 watch service planning and extend the polished UX patterns to upcoming watch/mv/search commands.

## 2025-10-21
- Implemented Phase 5 watch service (`dorgy watch`) with `--once`, JSON/quiet/summary parity, and configurable debounce/backoff sourced from `processing.watch` defaults.
- Added `WatchService` to batch filesystem events, reuse the ingestion/classification/organization pipeline, and persist incremental updates to `.dorgy/state.json`, `.dorgy/history.jsonl`, and `.dorgy/watch.log`.
- Documented the workflow in SPEC/README/AGENTS (including module-specific guidance) and introduced CLI integration tests in `tests/test_cli_watch.py` covering one-shot and JSON flows.
- Updated SPEC phase tracking and configuration snippets and refreshed README highlights to surface the new watch behaviour.

## 2025-10-22
- Delivered Phase 5.5 watch deletions/external moves: normalized events (`WatchEvent`), added `DeleteOperation` support, and wired state/history/log updates with removal notes plus JSON `removals`/`suppressed_deletions`.
- Introduced `processing.watch.allow_deletions` (default `false`) and `dorgy watch --allow-deletions`; CLI summaries now surface `deleted` counts and warn on executed or suppressed removals.
- Expanded watch tests to cover suppressed deletions, opt-in deletions, internal moves, and moves outside the collection, then refreshed README/SPEC/AGENTS guidance.
- Next actions: roll the enhanced watch metadata into upcoming Phase 6 CLI workflows (`search`, `mv`, extended status) and align automation documentation as new commands come online.

## 2025-10-23
- Implemented Phase 6 CLI surface additions: added `dorgy search` with tag/name/date filters plus JSON/count parity and introduced `dorgy mv` leveraging the operation executor for safe moves/renames, including conflict strategies and dry-run support.
- Centralized CLI option factories in `dorgy.cli.options`, added `_ProgressScope` for Rich progress instrumentation (wired into `org` and `watch --once`), and extended CLI configuration with `cli.progress_enabled`, `cli.search_default_limit`, and `cli.move_conflict_strategy`.
- Updated watch batch JSON to record `started_at`, `completed_at`, and `duration_seconds`; refreshed README, SPEC, and AGENTS documentation to describe new commands and configuration defaults.
- Added integration tests covering `dorgy search` filters/limits and `dorgy mv` execution, dry-run, and skip-conflict behaviour; introduced JSON assertions to guard new payload schemas.
- Instrumented classification calls with per-request timing, added configurable concurrency (`processing.parallel_workers`), and wired run-time progress so slow LLM responses can be diagnosed while multiple requests run in parallel.
- Next actions: continue Phase 6 polish (e.g., additional search filters, CLI UX refinements), validate progress output across terminals, and stage remaining Phase 6 scope before marking the phase complete.

## 2025-10-24
- Created `feature/ci-pipeline` branch and added `.github/workflows/ci.yml` to run Ruff lint/format checks, MyPy, and pytest via `uv` on pushes to `main` and pull requests.
- Updated SPEC Phase 8 status plus AGENTS directives to point contributors to the new CI entry point and its expected tooling coverage.
- Followed up on initial workflow failure by switching the sync step to `uv sync --extra dev --locked`, ensuring dev extras install cleanly in GitHub Actions.
- Adjusted the MyPy step to `uv run mypy src main.py` so the workflow targets our packages explicitly and avoids empty invocations.
- Resolved CI-only MyPy complaints by refining optional dependency shims for `python-magic` and `watchdog`, ensuring stub fallbacks use explicit ignores without clashing with module assignments.
- Next actions: monitor initial workflow runs, then expand coverage (matrix/caching or additional hooks) once baseline stability is confirmed.

## 2025-10-25
- Kicked off Phase 5.8 implementation by adding `VisionCaptioner` (DSPy image signature) plus `VisionCache` persistence, wiring ingestion to request captions when `processing.process_images` is enabled, and surfacing caption/label metadata on descriptors.
- Updated CLI and watch flows to instantiate the captioner, reuse cached results under `.dorgy/vision.json`, and persist caches post-run; errors now surface when the configured model lacks vision support.
- Enriched tags/previews with caption output, extended config defaults/documentation to the new `process_images` toggle, and added type hints to all DSPy signatures for consistency.
- Surfaced vision metadata in `org`/`watch` JSON payloads (new per-file `vision` object) and documented automation expectations in README/AGENTS.
- Persisted caption metadata into collection state records and added CLI coverage to verify prompts reach the captioner and stored records.
- Next actions: begin Phase 7 search/index planning, incorporating the enriched vision metadata into indexing requirements.

## 2025-10-26
- Implemented a DSPy logging filter to drop the structured-output fallback warnings so CLI dry runs stay focused on actionable results.
- Wired the filter into the classification engine, structure planner, and vision captioner initialization to keep suppression consistent across DSPy entry points.
- Next actions: monitor upcoming DSPy releases for logging changes and backfill regression coverage if the warning signatures evolve.

## 2025-10-27
- Hardened `VisionCaptioner` image loading by registering optional Pillow plugins (HEIF/AVIF/JXL) when available and falling back to Pillow conversions when DSPy cannot ingest a file directly.
- Added PNG conversion via in-memory buffers so HEIC/AVIF/JXL/ICO assets no longer trigger multimodal capability errors during captioning.
- `uv run pytest` remains green (68 passed, 1 skipped); monitor watch/org runs against HEIC collections to confirm the regression is resolved.
- Tweaked structure planner instructions to prioritise grouping files into directories so fewer items remain at the root level.

## 2025-10-28
- Added shared `--prompt-file` support for `dorgy org` and `dorgy watch`, loading UTF-8 instructions via `resolve_prompt_text` so file-based prompts override inline `--prompt` values and flow through JSON payloads.
- Extended CLI integration tests to cover prompt file precedence for both commands and verified via `uv run pytest tests/test_cli_org.py::test_cli_org_prompt_file_overrides_inline_prompt tests/test_cli_watch.py::test_cli_watch_prompt_file_overrides_inline_prompt`.
- Updated SPEC usage examples and CLI AGENTS guidance to document the new flag; next actions: monitor prompt-handling feedback and consider exposing prompt templates in config if automation asks for reusable defaults.

## 2025-10-29
- Spun up `feature/release-prep` for distribution work so metadata and publishing scripts stay isolated from `main`.
- Polished `pyproject.toml` with author, license, keywords, classifiers, and canonical project URLs to prep PyPI presentation; confirmed packaging still builds locally.
- Marked Phase 9 \"Distribution & Release Prep\" as in progress inside SPEC to track the new milestone.
- Next actions: document release expectations in AGENTS, run `uv run pre-commit run --all-files`, and stage TestPyPI dry run instructions.
- Completed TestPyPI dry run with `uv publish`, confirmed `dorgy` installs from the index, and smoke-tested the CLI (`dorgy --help`) in a clean environment.
- Next actions: prepare production PyPI token, rerun `uv build`/`uv publish`, tag `v0.1.0`, and merge the release branch once CI is green.
- Reduced CLI startup latency by deferring heavy imports via module-level lazy loaders, preserving monkeypatch-friendly attributes, and verified the new structure with `uv run pre-commit run --all-files`.

## 2025-10-30
- Introduced Invoke automation (`tasks.py`) that wraps uv for sync/build/version/publish/test/lint flows so contributors have a consistent entry point for release chores.
- Added `invoke` to the dev extra, refreshed `uv.lock`, and ran `uv sync --extra dev` so local environments pick up the dependency.
- Verified availability with `uv run invoke --list`, confirming release/test/ci tasks show up alongside the new helpers.
- Added git tagging Invoke task (`invoke tag-version`) and extended `invoke release` to support tagging/pushing `v<version>` after publishes.
- Release automation now stages and commits `pyproject.toml`/`uv.lock` after version bumps so tagging always lands on a clean tree.
- Addressed CI-only failure in `test_cli_org_prompt_file_overrides_inline_prompt` by writing a real PNG via Pillow so python-magic detects it as an image across Linux runners.
- Next actions: surface the Invoke collection in README release guidance and decide whether SPEC Phase 9 should reference the `invoke release` path explicitly.

## 2025-10-31
- Defaulted `processing.process_images` to true and `organization.rename_files` to false, updating `dorgy.config.models`, module AGENTS guidance, and CLI docs to reflect the new expectations.
- Softened CLI/watch vision initialization so missing LLM credentials fall back to non-vision runs while surfacing plan notes and warnings for automation.
- Documented provider-specific LLM setup (OpenAI, Anthropic, xAI, Google Gemini, local gateways) in README to help operators wire credentials via `dorgy config`.
- Verified rename/vision regression coverage with `uv run pytest tests/test_cli_org.py::test_cli_org_renames_files_when_enabled`; next actions: broaden watch JSON tests to assert the vision-captioning warning note propagates when captioning is auto-disabled.

## 2025-11-01
- Hardened structure planning by normalizing DSPy responses that wrap JSON in conversational text or fenced code blocks, ensuring LLM proposals drive destination maps instead of falling back to category folders.
- Added dedicated coverage in `tests/test_structure_planner.py` for the new decoding helper and refreshed AGENTS guidance so future prompt tweaks keep the parser/test expectations aligned.
- `uv run pytest` passes locally (79 passed, 1 skipped); next actions: capture a regression fixture from a real organization run to validate the end-to-end tree output once the planner is consistently returning JSON.
- Enforced DSPy as the default path by raising `LLMUnavailableError` when classification/structure planning runs without the fallback flag and `LLMResponseError` when responses are unusable, propagating rich CLI errors so operators configure credentials instead of silently hitting heuristics.
- Updated undo flow to prune empty directories created during organization (guarded by the original snapshot directory list) so rollbacks leave the collection tree identical to its pre-org state; added integration coverage under `tests/test_cli_org.py::test_cli_undo_removes_empty_directories`.

## 2025-11-02
- Refactored LLM configuration to rely solely on a single LiteLLM-style `llm.model` string so DSPy receives the exact identifier without auxiliary provider fields.
- Tightened fallback behaviour so classification/structure heuristics only execute when `DORGY_USE_FALLBACKS=1`; runtime errors now bubble immediately when fallbacks are disabled.
- Updated DSPy wiring to avoid injecting placeholder API credentials, refreshed README/SPEC/ARCH/AGENTS guidance, and renamed the fallback environment variable across tests and docs.
- Swapped the default model to `openai/gpt-5`, updating tests/docs to match and keeping local gateway examples pointed at `ollama/<model>` where appropriate.
- Surfaced `context.llm` metadata and an LLM summary line in `dorgy org`/`watch` outputs so operators can audit which model and parameters produced a run.
- Next actions: run `uv run pytest` after final cleanup, validate CLI error messaging for misconfigured `llm.model` values, and determine whether migration tooling should warn users with legacy configs.

## 2025-11-03
- Landed configurable preview limits by wiring `processing.preview_char_limit` through config models, `MetadataExtractor`, CLI, and watch service; descriptors now record `preview_limit_characters` alongside longer previews.
- Extended ingestion tests to cover the new limit behaviour and documented the knob in ARCH, SPEC, and AGENTS guidance.
- Next actions: fan out the new config field to config CLI validation/help text and run the full `uv run pre-commit run --all-files` sweep once adjacent config docs are refreshed.

## 2025-10-21
- Added `_coerce_confidence` normalization to `ClassificationEngine`, prompting DSPy for decimal confidences and reusing the helper for vision caption scores so low-certainty checks aren't tripped by malformed model outputs.
- Lowered the default `ambiguity.confidence_threshold` to 0.60, refreshed SPEC/ARCH/config AGENTS guidance, and aligned CLI integration tests with the new review semantics.
- Bumped project version to 0.2.0 in `pyproject.toml`/`uv.lock`, ran the full pre-commit suite (Ruff, MyPy, pytest) to confirm the tree is release-ready, and staged documentation updates ahead of publishing.
- Next actions: capture release notes for 0.2.0, push the feature branch, and open a PR before running the TestPyPI/PyPI release workflow.
- Added a shared shutdown manager that traps SIGINT/SIGTERM, sets a global event, and teaches ingestion/classification/watch loops to poll it so Ctrl+C ends runs cleanly without leaking threads.

## 2025-11-04
- Added a GitHub Actions build badge to `README.md` so the CI status is visible from the project landing page.
- Ran `uv run pre-commit run --all-files` (Ruff, Ruff format, MyPy, pytest) to validate the tree before committing.
- Next actions: monitor the README badge after merge to confirm it renders the expected passing/failing state from `main`.

## 2025-11-05
- Threaded organizer prompts into `StructurePlanner.propose`, updated CLI call sites, and extended coverage/AGENTS/ARCH guidance so structure recommendations respect user instructions.
- Next actions: run `uv run pytest tests/test_structure_planner.py` and `uv run pre-commit run --files src/dorgy/classification/structure.py tests/test_structure_planner.py` before opening the PR.
- Introduced `--classify-prompt`/`--structure-prompt` (plus file variants) on `org`/`watch`, split prompt plumbing across classification and structure planning, refreshed docs/tests, and kept JSON compatibility via legacy `context.prompt`.
- Next actions: execute `uv run pre-commit run --files src/dorgy/cli.py src/dorgy/cli_support.py src/dorgy/watch/service.py tests/test_cli_org.py tests/test_cli_watch.py` and `uv run pytest tests/test_cli_org.py tests/test_cli_watch.py` before merging.
