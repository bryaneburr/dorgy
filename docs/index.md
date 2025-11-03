# Dorgy

An AI‑assisted CLI that keeps growing collections of files tidy. Dorgy ingests, classifies, and organizes files on demand or continuously, preserves a reversible audit trail, and powers portable per‑collection semantic search.

## What You Can Do

- Organize folders: classify, rename, and move files safely with undo.
- Watch directories: batch changes with debouncing and emit JSON for automation.
- Search collections: substring and semantic queries using a local Chromadb index.
- Move safely: rename/move tracked files while preserving history and search metadata.

## Quick Start

```bash
dorgy --help
dorgy org ./documents --dry-run
dorgy watch ./inbox --json --once
```

See Getting Started → Quickstart and Configuration for more.

## Features at a Glance

- DSPy‑backed classification with heuristic fallbacks and vision captions (opt‑in by config).
- Reversible operations with `.dorgy/` state, history, quarantine, and needs‑review staging.
- Per‑collection Chromadb search store under `.dorgy/chroma` + `search.json` manifest.
- Shared CLI UX: quiet/summary/JSON modes and standardized error payloads.

## Learn More

- Getting Started: Installation, Quickstart, Configuration
- Guides: Organize, Watch, Search, Move & Undo, Prompts & Vision, Troubleshooting
- Reference: CLI, API, Config, On‑Disk Layout, JSON contracts
- Explanations: Architecture, Design Choices, Search Architecture

If you’re contributing, see Development → Contributing and CI.
