# Guide: Organize

`dorgy org` ingests files, classifies them, plans moves/renames, and applies changes with audit history and undo support.

Basic usage:

```bash
dorgy org . --dry-run
dorgy org .
```

Common options:

- `-r, --recursive` — include subdirectories.
- `--classify-prompt/--classify-prompt-file` — guidance for classification.
- `--structure-prompt/--structure-prompt-file` — folder planning guidance (defaults to classify guidance when omitted).
- `--output` — copy mode to a destination root.
- `--with-search` / `--without-search` — control per-run search indexing.
- Presentation: `--json`, `--summary`, `--quiet` (not all combinations are allowed).

Summary lines and standardized JSON payloads are shared across commands; see Reference → JSON.
