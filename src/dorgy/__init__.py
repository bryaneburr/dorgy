"""Top-level package for the Dorgy CLI."""

from importlib import metadata as _metadata

__all__ = ["__version__"]


def __getattr__(name: str):
    if name == "__version__":
        return _metadata.version("dorgy")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(list(globals().keys()) + ["__version__"])
