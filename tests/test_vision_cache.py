"""Tests covering the vision caption caching utilities."""

from pathlib import Path

from dorgy.classification import VisionCache, VisionCaption


def test_vision_cache_round_trip(tmp_path: Path) -> None:
    """Ensure caption results persist to disk and load correctly."""

    cache_path = tmp_path / "vision.json"
    cache = VisionCache(cache_path)

    caption = VisionCaption(
        caption="A spacecraft launching into the night sky.",
        labels=["Space", "Launch"],
        confidence=0.92,
        reasoning="Visible rocket plume and night setting.",
    )

    cache.set("hash123", caption)
    cache.save()

    reloaded = VisionCache(cache_path)
    reloaded.load()
    result = reloaded.get("hash123")
    assert result is not None
    assert result.caption == caption.caption
    assert result.labels == caption.labels
    assert result.confidence == caption.confidence
    assert result.reasoning == caption.reasoning


def test_vision_cache_returns_none_for_missing_keys(tmp_path: Path) -> None:
    """Verify cache lookups return None when entries are absent."""

    cache = VisionCache(tmp_path / "vision.json")
    cache.load()
    assert cache.get("missing") is None
