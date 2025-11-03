# Troubleshooting

- Missing state: run `dorgy org <root>` before commands like `mv`, `search`, and `undo`.
- JSON + quiet/summary conflicts: `--json` cannot be combined with `--quiet` or `--summary`.
- Watch deletions suppressed: enable `--allow-deletions` or set `processing.watch.allow_deletions: true`.
- Search index missing: initialize via `dorgy search <root> --init-store` or re-run `dorgy org` without `--without-search`.
- Permission errors during move: ensure files are available and not locked by other processes.

See Reference → JSON → Errors for standardized payload shapes and error codes.
