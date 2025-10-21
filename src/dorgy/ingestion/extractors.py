"""Content and metadata extraction helpers."""

from __future__ import annotations

import importlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, cast

DocumentConverter: Any = None
InputFormat: Any = None
_DOCLING_LOG_NAMES: list[str] = []
_DOCLING_DEFAULT_LEVELS: dict[str, int] = {}

_docling_datamodel: Any = None
_docling_converter_module: Any = None

try:  # pragma: no cover - optional dependency
    _docling_datamodel = importlib.import_module("docling.datamodel.base_models")
    _docling_converter_module = importlib.import_module("docling.document_converter")
except ImportError:  # pragma: no cover
    pass
else:
    InputFormat = getattr(_docling_datamodel, "InputFormat", None)
    DocumentConverter = getattr(_docling_converter_module, "DocumentConverter", None)

if InputFormat is not None and DocumentConverter is not None:
    _DOCLING_LOG_NAMES = [
        "docling",
        "docling_core",
        "docling.document_converter",
        "docling.pipeline.standard_pdf_pipeline",
        "docling.pipeline.standard_docx_pipeline",
        "docling.backend.docling_parse_v4_backend",
    ]
    _DOCLING_DEFAULT_LEVELS = {}
    for _name in _DOCLING_LOG_NAMES:
        logger = logging.getLogger(_name)
        _DOCLING_DEFAULT_LEVELS[_name] = logger.level
        logger.setLevel(logging.ERROR)
else:
    InputFormat = None
    DocumentConverter = None
    _DOCLING_LOG_NAMES = []
    _DOCLING_DEFAULT_LEVELS = {}

try:  # pragma: no cover - optional dependency
    from PIL import ExifTags, Image
except ImportError:  # pragma: no cover - executed when Pillow missing
    Image = cast(Any, None)
    ExifTags = cast(Any, None)


class MetadataExtractor:
    """Extract structured metadata and previews for a file."""

    _DEFAULT_PREVIEW_CHAR_LIMIT = 2048
    _DOC_PREVIEW_MAX_PAGES = 3

    _DOC_MIME_MAP = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/msword": "docx",
        "application/vnd.ms-powerpoint": "pptx",
        "application/vnd.ms-excel": "xlsx",
        "text/markdown": "md",
        "text/csv": "csv",
        "text/html": "html",
    }

    def __init__(self, preview_char_limit: int | None = None) -> None:
        """Initialise the metadata extractor and supporting converters.

        Args:
            preview_char_limit: Maximum number of characters to retain in previews. When
                omitted, a sensible default is applied.
        """

        self._docling_converter: Any | None = None
        self._docling_lock = threading.Lock()
        self._docling_preview_cache: dict[Path, str] = {}
        self._docling_enabled: bool = DocumentConverter is not None
        limit = (
            preview_char_limit
            if preview_char_limit is not None and preview_char_limit > 0
            else self._DEFAULT_PREVIEW_CHAR_LIMIT
        )
        self._preview_char_limit = limit

    def extract(
        self, path: Path, mime_type: str, sample_limit: int | None = None
    ) -> Dict[str, str]:
        """Return metadata key/value pairs for the file.

        Args:
            path: Path to the file being processed.
            mime_type: MIME type detected for the file.
            sample_limit: Optional limit on the number of bytes to sample.

        Returns:
            Dict[str, str]: Mapping of metadata field names to values.
        """
        try:
            stat = path.stat()
        except OSError as exc:  # pragma: no cover - file disappeared
            return {"error": str(exc)}

        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        metadata: Dict[str, str] = {
            "size_bytes": str(stat.st_size),
            "modified_at": modified.isoformat(),
            "mime_type": mime_type,
        }

        effective_preview_limit = (
            min(sample_limit, self._preview_char_limit)
            if sample_limit
            else self._preview_char_limit
        )
        metadata["preview_limit_characters"] = str(effective_preview_limit)

        if mime_type.startswith("text") or mime_type in {"application/json", "application/xml"}:
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    sample = fh.read(effective_preview_limit)
            except OSError:
                sample = ""
            if sample:
                metadata["sampled_characters"] = str(len(sample))
                metadata["sampled_lines"] = str(sample.count("\n") + 1)
        if mime_type == "application/json":
            try:
                with path.open("r", encoding="utf-8") as fh:
                    obj = json.load(fh)
                if isinstance(obj, dict):
                    metadata["json_keys"] = str(len(obj))
            except Exception:  # pragma: no cover - best effort
                pass
        if mime_type.startswith("image/") and Image is not None:
            try:
                with Image.open(path) as img:
                    width, height = img.size
                    metadata["image_width"] = str(width)
                    metadata["image_height"] = str(height)
                    metadata["image_mode"] = img.mode
                    if ExifTags and img.getexif():
                        exif_data = img.getexif()
                        orientation_key = next(
                            (k for k, v in ExifTags.TAGS.items() if v == "Orientation"),
                            None,
                        )
                        if orientation_key and orientation_key in exif_data:
                            metadata["image_orientation"] = str(exif_data[orientation_key])
            except Exception:  # pragma: no cover - corrupt images
                pass

        docling_result = self._docling_metadata(path, mime_type, sample_limit)
        if docling_result is not None:
            extra_metadata, preview = docling_result
            metadata.update(extra_metadata)
            if preview:
                self._docling_preview_cache[path] = preview

        return metadata

    def preview(self, path: Path, mime_type: str, sample_limit: int | None = None) -> Optional[str]:
        """Return a short textual preview of the file content.

        Args:
            path: Path to the file being processed.
            mime_type: MIME type detected for the file.
            sample_limit: Optional limit on the number of bytes to sample.

        Returns:
            Optional[str]: Preview text when available, otherwise None.
        """
        if mime_type.startswith("text") or mime_type in {"application/json", "application/xml"}:
            limit = (
                min(sample_limit, self._preview_char_limit)
                if sample_limit
                else self._preview_char_limit
            )
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    snippet = fh.read(limit).strip()
            except OSError:
                return None
            return snippet or None
        cached = self._docling_preview_cache.pop(path, None)
        if cached:
            limit = (
                min(sample_limit, self._preview_char_limit)
                if sample_limit
                else self._preview_char_limit
            )
            return cached[:limit].strip() or None

        docling_preview = self._docling_preview(path, mime_type, sample_limit)
        if docling_preview:
            return docling_preview
        return None

    # ------------------------------------------------------------------ #
    # Docling helpers                                                    #
    # ------------------------------------------------------------------ #

    def _docling_metadata(
        self,
        path: Path,
        mime_type: str,
        sample_limit: int | None,
    ) -> tuple[dict[str, str], Optional[str]] | None:
        """Extract metadata/preview using Docling when available."""

        converter = self._get_docling_converter()
        if converter is None:
            return None

        fmt = self._docling_format_for_mime(mime_type)
        if fmt is None:
            return None

        original_levels = {}
        for name in _DOCLING_LOG_NAMES:
            logger = logging.getLogger(name)
            original_levels[name] = logger.level
            logger.setLevel(logging.CRITICAL)

        try:
            result = converter.convert(
                str(path),
                max_num_pages=self._DOC_PREVIEW_MAX_PAGES,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            message = str(exc).lower()
            if "password" in message or "incorrect password" in message:
                logging.getLogger(__name__).info(
                    "Skipping Docling extraction for password-protected file: %s", path
                )
                return (
                    {"password_protected": "true", "mime_type": mime_type},
                    "Password protected file",
                )
            logging.getLogger(__name__).debug("Docling conversion failed for %s: %s", path, exc)
            return None
        finally:
            for name, level in original_levels.items():
                logging.getLogger(name).setLevel(level)

        if not getattr(result, "document", None):
            return None

        metadata: dict[str, str] = {}
        try:
            if hasattr(result.document, "num_pages"):
                metadata["pages"] = str(result.document.num_pages)
        except Exception:  # pragma: no cover - defensive
            pass

        preview_text = result.document.export_to_text()
        if not preview_text:
            return metadata, None

        limit = (
            min(sample_limit, self._preview_char_limit)
            if sample_limit
            else self._preview_char_limit
        )
        snippet = preview_text.strip()[:limit].strip()
        return metadata, snippet or None

    def _docling_preview(
        self,
        path: Path,
        mime_type: str,
        sample_limit: int | None,
    ) -> Optional[str]:
        """Compute previews on demand when not captured during metadata extraction."""

        result = self._docling_metadata(path, mime_type, sample_limit)
        if result is None:
            return None
        metadata, preview = result
        if metadata:
            # When preview is requested before metadata, ensure docling metadata is
            # cached for later reuse during the metadata phase.
            self._docling_preview_cache[path] = preview or ""
        return preview

    def _docling_format_for_mime(self, mime_type: str) -> Optional[InputFormat]:
        if not self._docling_enabled or InputFormat is None:
            return None
        mapped = self._DOC_MIME_MAP.get(mime_type.lower())
        if mapped is None:
            return None
        try:
            return InputFormat(mapped)
        except ValueError:  # pragma: no cover - unsupported mapping
            return None

    def _get_docling_converter(self) -> Optional[DocumentConverter]:
        if not self._docling_enabled or DocumentConverter is None:
            return None
        if self._docling_converter is not None:
            return self._docling_converter
        with self._docling_lock:
            if self._docling_converter is None:
                for name in (
                    "docling",
                    "docling_core",
                    "docling.document_converter",
                    "docling.pipeline.standard_pdf_pipeline",
                    "docling.pipeline.standard_docx_pipeline",
                ):
                    logging.getLogger(name).setLevel(logging.ERROR)
                self._docling_converter = DocumentConverter()
        return self._docling_converter
