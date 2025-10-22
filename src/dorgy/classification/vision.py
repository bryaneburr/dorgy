"""DSPy-powered helpers for extracting image captions and labels."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - optional dependency
    import dspy  # type: ignore
except ImportError:  # pragma: no cover - executed when DSPy absent
    dspy = None  # type: ignore[assignment]

from dorgy.classification.dspy_logging import configure_dspy_logging
from dorgy.config.models import LLMSettings

from .cache import VisionCache
from .engine import _coerce_confidence
from .models import VisionCaption

LOGGER = logging.getLogger(__name__)

_PILLOW_PLUGINS_INITIALISED = False


def _ensure_pillow_plugins_registered() -> None:
    """Register optional Pillow image plugins (HEIF/AVIF/JXL) when available."""

    global _PILLOW_PLUGINS_INITIALISED
    if _PILLOW_PLUGINS_INITIALISED:
        return

    plugin_specs: tuple[tuple[tuple[str, ...], str | None], ...] = (
        (("pillow_heif",), "register_heif_opener"),
        (("pillow_avif",), "register_avif_opener"),
        (("pillow_jxl",), "register_jxl_opener"),
    )

    for module_names, registrar in plugin_specs:
        module = None
        module_name = None
        for candidate in module_names:
            try:
                module = importlib.import_module(candidate)
                module_name = candidate
                break
            except ImportError:
                continue

        if module is None:
            continue

        registration_fn = getattr(module, registrar, None) if registrar else None
        if callable(registration_fn):
            try:
                registration_fn()
            except Exception as exc:  # pragma: no cover - registration best effort
                LOGGER.debug(
                    "Failed to register Pillow plugin %s via %s: %s",
                    module_name,
                    registrar,
                    exc,
                )
                continue
        elif registrar:
            LOGGER.debug(
                "Pillow plugin %s does not expose %s; assuming import side effects.",
                module_name,
                registrar,
            )

    _PILLOW_PLUGINS_INITIALISED = True


class VisionCaptioner:
    """Generate captions and labels for images using a DSPy program."""

    def __init__(
        self,
        settings: Optional[LLMSettings] = None,
        *,
        cache: Optional[VisionCache] = None,
    ) -> None:
        """Initialise the captioner with the configured LLM settings.

        Args:
            settings: LLM configuration shared with the text classifier.
            cache: Optional cache used to persist captioning results.

        Raises:
            RuntimeError: If DSPy is unavailable or the language model cannot be configured.
        """

        if dspy is None:
            raise RuntimeError(
                (
                    "Image captioning requires DSPy with vision-capable models. "
                    "Install DSPy or disable process_images in your configuration."
                )
            )

        self._settings = settings or LLMSettings()
        self._cache = cache
        if self._cache is not None:
            self._cache.load()
        configure_dspy_logging()
        self._configure_language_model()
        self._program = self._build_program()
        self._fatal_error: str | None = None

    def caption(
        self,
        path: Path,
        *,
        cache_key: Optional[str],
        prompt: Optional[str] = None,
    ) -> Optional[VisionCaption]:
        """Return a caption/label bundle for the supplied image.

        Args:
            path: Absolute path to the image.
            cache_key: Deterministic key (typically the file hash) for caching.
            prompt: Optional override that augments the base caption prompt.

        Returns:
            Optional[VisionCaption]: Captioning result or ``None`` when unavailable.
        """

        if self._fatal_error is not None:
            LOGGER.debug(
                "Skipping vision captioning for %s due to prior fatal error: %s",
                path,
                self._fatal_error,
            )
            return None

        if cache_key and self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        image_input = self._load_image(path)
        base_prompt = (
            "Provide a concise 1-2 sentence caption describing the image. Include key objects, "
            "notable text, and overall context. Also return a short list of 3-5 labels that would "
            "help organize similar images."
        )
        full_prompt = f"{base_prompt}\n\nAdditional context: {prompt}" if prompt else base_prompt

        try:
            response = self._program(image=image_input, prompt=full_prompt)
        except Exception as exc:  # pragma: no cover - DSPy runtime errors
            error_message = self._format_exception(exc)
            LOGGER.debug("Vision captioner failed: %s", error_message)
            self._fatal_error = error_message
            raise RuntimeError(
                "Image captioning failed. The configured LLM rejected the image request. "
                "Provider response: "
                f"{error_message}. Configure a multimodal-capable model or disable "
                "`process_images`."
            ) from exc

        caption_text = getattr(response, "caption", "") if response else ""
        if not caption_text:
            return None

        labels = getattr(response, "labels", []) or []
        if not isinstance(labels, list):
            labels = []
        confidence_raw = getattr(response, "confidence", None)
        confidence = None
        if confidence_raw not in ("", None):
            confidence = _coerce_confidence(confidence_raw)
        reasoning = getattr(response, "reasoning", None)

        result = VisionCaption(
            caption=caption_text.strip(),
            labels=[label.strip() for label in labels if isinstance(label, str) and label.strip()],
            confidence=confidence,
            reasoning=reasoning.strip()
            if isinstance(reasoning, str) and reasoning.strip()
            else None,
        )

        if cache_key and self._cache is not None:
            self._cache.set(cache_key, result)
        return result

    def save_cache(self) -> None:
        """Persist cached captioning results."""

        if self._cache is not None:
            self._cache.save()

    @property
    def fatal_error(self) -> Optional[str]:
        """Return the last fatal error reported by the captioner, if any."""

        return self._fatal_error

    def _configure_language_model(self) -> None:
        """Configure the DSPy language model according to LLM settings."""

        default_settings = LLMSettings()
        configured = any(
            [
                self._settings.api_base_url,
                self._settings.api_key,
                self._settings.model != default_settings.model,
            ]
        )
        if not configured:
            raise RuntimeError(
                (
                    "Vision captioning requires an explicitly configured LLM. "
                    "Update your configuration with an LLM model that supports images."
                )
            )

        lm_kwargs: dict[str, object] = {
            "model": self._settings.model,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }

        if self._settings.api_base_url:
            lm_kwargs["api_base"] = self._settings.api_base_url
        if self._settings.api_key is not None and self._settings.api_key != "":
            lm_kwargs["api_key"] = self._settings.api_key

        try:
            language_model = dspy.LM(**lm_kwargs)
            dspy.settings.configure(lm=language_model)
        except Exception as exc:  # pragma: no cover - DSPy configuration errors
            raise RuntimeError(
                "Unable to configure the DSPy language model for image captioning. Verify your LLM "
                "settings or disable process_images."
            ) from exc

    @staticmethod
    def _build_program():
        """Construct the DSPy program used for image captioning."""

        class ImageCaptionSignature(dspy.Signature):  # type: ignore[misc]
            """Return a caption, labels, and confidence for an image."""

            image: "dspy.Image" = dspy.InputField()
            prompt: str = dspy.InputField()
            caption: str = dspy.OutputField()
            labels: list[str] = dspy.OutputField()
            confidence: str = dspy.OutputField()
            reasoning: str = dspy.OutputField()

        return dspy.Predict(ImageCaptionSignature)

    @staticmethod
    def _load_image(path: Path):
        """Return a DSPy image payload for the supplied path."""

        errors: list[str] = []

        if hasattr(dspy.Image, "from_path"):
            try:
                return dspy.Image.from_path(str(path))
            except Exception as exc:  # pragma: no cover - DSPy backend specifics
                LOGGER.debug("dspy.Image.from_path failed for %s: %s", path, exc)
                errors.append(f"from_path: {exc}")
        if hasattr(dspy.Image, "from_file"):
            try:
                return dspy.Image.from_file(str(path))
            except Exception as exc:  # pragma: no cover - DSPy backend specifics
                LOGGER.debug("dspy.Image.from_file failed for %s: %s", path, exc)
                errors.append(f"from_file: {exc}")
        if hasattr(dspy.Image, "from_bytes"):
            data = path.read_bytes()
            try:
                return dspy.Image.from_bytes(data)
            except Exception as exc:  # pragma: no cover - DSPy backend specifics
                LOGGER.debug("dspy.Image.from_bytes failed for %s: %s", path, exc)
                errors.append(f"from_bytes: {exc}")

        converted = VisionCaptioner._load_via_pillow(path)
        if converted is not None and hasattr(dspy.Image, "from_PIL"):
            try:
                return dspy.Image.from_PIL(converted)
            except Exception as exc:  # pragma: no cover - conversion errors
                LOGGER.debug("dspy.Image.from_PIL failed for %s: %s", path, exc)
                errors.append(f"from_PIL: {exc}")

        details = "; ".join(errors) if errors else "No valid DSPy image constructors available."
        raise RuntimeError(
            "Unable to construct a DSPy image payload from the provided path: "
            f"{path}. Details: {details}"
        )

    @staticmethod
    def _load_via_pillow(path: Path):
        """Open the file via Pillow and return a converted RGB image when possible."""

        try:
            from PIL import Image
        except ImportError:  # pragma: no cover - Pillow optional
            LOGGER.debug("Pillow is not installed; cannot convert %s", path)
            return None

        _ensure_pillow_plugins_registered()

        try:
            with Image.open(path) as image:
                converted = image.convert("RGB")
                converted.load()
        except Exception as exc:
            LOGGER.debug("Pillow failed to load %s: %s", path, exc)
            return None

        return converted

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        """Return a normalized string describing the supplied exception."""

        message = str(exc).strip()
        if not message:
            message = repr(exc)
        return f"{exc.__class__.__name__}: {message}"
