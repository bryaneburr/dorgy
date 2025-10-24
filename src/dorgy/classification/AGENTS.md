# CLASSIFICATION COORDINATION NOTES

- `ClassificationEngine` encapsulates DSPy programs; keep DSPy imports isolated here so the rest of the codebase can function without the dependency.
- All new classification inputs should be wrapped in `ClassificationRequest` (descriptor + prompt + collection context) to keep interfaces consistent.
- Update `ClassificationDecision` / `ClassificationBatch` when adding new outputs (e.g., audit trails) and ensure downstream state persistence handles them.
- Unit tests for classification scaffolding live under `tests/`; mock DSPy interactions to keep the suite hermetic.
- The heuristic fallback should remain deterministic; adjust `tests/test_classification_engine.py` if logic changes.
- `ClassificationCache` persists decisions in `.dorgy/classifications.json`. Respect dry-run semantics and remember to guard writes behind the rename toggle.
- `VisionCaptioner` wraps DSPy image signatures; it should fail fast when the configured model lacks vision support and reuse `VisionCache` entries in `.dorgy/vision.json` to limit repeat calls. Pass user prompts through when available so descriptors and downstream consumers receive context-aware captions.
- DSPy runs by default; set `DORGY_USE_FALLBACKS=1` only when explicitly testing the heuristic classifier (CI, local dev). Without the flag, missing/misconfigured LLMs raise `LLMUnavailableError` and malformed responses raise `LLMResponseError` so CLI commands surface actionable errors instead of silently degrading to heuristics.
- `LLMSettings` expects LiteLLM-style `llm.model` values (e.g., `openai/gpt-4o-mini`); rely solely on the model string when wiring new integrations so configuration stays aligned with LiteLLM conventions.
- Structure planner responses may include conversational wrapping or fenced code blocks; keep `_decode_tree_payload` and `tests/test_structure_planner.py` in sync when adjusting accepted output formats.
- `StructurePlanner.propose` now accepts the organizer prompt; append user guidance to the base instructions and ignore blank strings so CLI/watch callers can reuse existing prompt handling without leaking empty payloads.
- DSPy integration pulls runtime settings from `DorgyConfig.llm`; when adding new parameters (e.g., custom gateways) keep the configuration model, CLI overrides, and LM wiring in sync.
- DSPy outputs often provide non-numeric confidence values; reuse `_coerce_confidence` when new call sites surface model confidence so downstream review thresholds stay consistent across classifiers.
