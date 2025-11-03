# Guide: Prompts & Vision

Prompts

- `--classify-prompt` / `--classify-prompt-file` influence classification.
- `--structure-prompt` / `--structure-prompt-file` influence folder planning; defaults to classification guidance when omitted.

Vision

- Image captioning is enabled by default (`processing.process_images: true`).
- Captions are cached in `.dorgy/vision.json` and reused.
- Respect preview limits via `processing.preview_char_limit`.

Forward prompts via CLI so automation consumers receive consistent metadata in JSON summaries.

Examples:

```bash
dorgy org . --classify-prompt "Highlight tax documents"
dorgy watch . --once --structure-prompt-file prompts/structure.txt
```
