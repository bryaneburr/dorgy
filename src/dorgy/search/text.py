"""Text normalization utilities for search indexing."""

from __future__ import annotations

import re

from dorgy.ingestion import FileDescriptor

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_WHITESPACE = re.compile(r"\s+")


def normalize_search_text(text: str, *, limit: int = 4096) -> str:
    """Return sanitized text suitable for Chromadb document payloads.

    Args:
        text: Source text extracted from previews or captions.
        limit: Maximum number of characters retained in the normalized output.

    Returns:
        str: Normalized text with control characters removed, whitespace collapsed,
        and length capped to ``limit`` characters when ``limit`` is positive.
    """

    sanitized = _CONTROL_CHARS.sub(" ", text)
    sanitized = _WHITESPACE.sub(" ", sanitized).strip()
    if limit > 0:
        return sanitized[:limit]
    return sanitized


def descriptor_document_text(descriptor: FileDescriptor) -> str | None:
    """Return the best available textual content for a descriptor.

    Args:
        descriptor: Ingestion descriptor containing previews/metadata.

    Returns:
        Optional[str]: Raw text suitable for downstream normalization, or ``None``
        when no preview/caption data is available.
    """

    if descriptor.preview:
        return descriptor.preview

    caption = descriptor.metadata.get("vision_caption")
    labels = descriptor.metadata.get("vision_labels")
    label_text: str | None = None
    if isinstance(labels, str):
        label_text = labels.strip() or None
    elif isinstance(labels, list):
        label_text = ", ".join(str(label).strip() for label in labels if str(label).strip())
    if caption:
        if label_text:
            return f"{caption.strip()}\nLabels: {label_text}"
        return caption.strip() or None

    return None


__all__ = ["normalize_search_text", "descriptor_document_text"]
