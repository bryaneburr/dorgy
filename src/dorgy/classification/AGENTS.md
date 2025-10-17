# CLASSIFICATION COORDINATION NOTES

- `ClassificationEngine` encapsulates DSPy programs; keep DSPy imports isolated here so the rest of the codebase can function without the dependency.
- All new classification inputs should be wrapped in `ClassificationRequest` (descriptor + prompt + collection context) to keep interfaces consistent.
- Update `ClassificationDecision` / `ClassificationBatch` when adding new outputs (e.g., audit trails) and ensure downstream state persistence handles them.
- Unit tests for classification scaffolding live under `tests/`; mock DSPy interactions to keep the suite hermetic.
- The heuristic fallback should remain deterministic; adjust `tests/test_classification_engine.py` if logic changes.
- `ClassificationCache` persists decisions in `.dorgy/classifications.json`. Respect dry-run semantics and remember to guard writes behind the rename toggle.
- DSPy runs by default; set `DORGY_USE_FALLBACK=1` only when explicitly testing the heuristic classifier (CI, local dev).
- DSPy integration pulls runtime settings from `DorgyConfig.llm`; when adding new parameters (e.g., custom gateways) keep the configuration model, CLI overrides, and LM wiring in sync.
