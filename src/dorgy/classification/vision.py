"""DSPy-powered helpers for extracting image captions and labels."""

from __future__ import annotations

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
from .models import VisionCaption

LOGGER = logging.getLogger(__name__)


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
            LOGGER.debug("Vision captioner failed: %s", exc)
            raise RuntimeError(
                (
                    "Image captioning failed. Ensure your configured LLM model "
                    "supports multimodal inputs."
                )
            ) from exc

        caption_text = getattr(response, "caption", "") if response else ""
        if not caption_text:
            return None

        labels = getattr(response, "labels", []) or []
        if not isinstance(labels, list):
            labels = []
        try:
            confidence = float(getattr(response, "confidence", ""))
        except (TypeError, ValueError):
            confidence = None
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

    def _configure_language_model(self) -> None:
        """Configure the DSPy language model according to LLM settings."""

        default_settings = LLMSettings()
        configured = any(
            [
                self._settings.api_base_url,
                self._settings.api_key,
                self._settings.provider != default_settings.provider,
                self._settings.model != default_settings.model,
            ]
        )
        if not configured:
            raise RuntimeError(
                (
                    "Vision captioning requires an explicitly configured LLM. "
                    "Update your configuration with a provider/model that supports images."
                )
            )

        api_key_missing = self._settings.api_key is None

        if self._settings.api_base_url and api_key_missing:
            self._settings.api_key = ""
            api_key_missing = False

        if (
            self._settings.provider
            and self._settings.provider != "local"
            and self._settings.api_base_url is None
            and api_key_missing
        ):
            raise RuntimeError(
                (
                    "An API key is required for the configured vision provider. "
                    "Update `llm.api_key` or disable process_images."
                )
            )

        lm_kwargs: dict[str, object] = {
            "model": self._settings.model,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }

        if self._settings.api_base_url:
            lm_kwargs["api_base"] = self._settings.api_base_url
        elif self._settings.provider:
            lm_kwargs["provider"] = self._settings.provider

        if self._settings.api_key is not None:
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

        if hasattr(dspy.Image, "from_path"):
            return dspy.Image.from_path(str(path))
        if hasattr(dspy.Image, "from_file"):
            return dspy.Image.from_file(str(path))
        if hasattr(dspy.Image, "from_bytes"):
            data = path.read_bytes()
            return dspy.Image.from_bytes(data)
        raise RuntimeError("Unable to construct a DSPy image payload from the provided path.")
