"""Top-level package for the Dorgy CLI."""

from importlib import metadata as _metadata

__all__ = ["__version__"]


def __getattr__(name: str):
    """Return dynamic module attributes supported by the package.

    Args:
        name: Attribute name being requested.

    Returns:
        str: Package version when `__version__` is requested.

    Raises:
        AttributeError: If the requested attribute is not supported.
    """
    if name == "__version__":
        return _metadata.version("dorgy")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """Return the list of attributes available on the package module.

    Returns:
        list[str]: Sorted collection of attribute names.
    """
    return sorted(list(globals().keys()) + ["__version__"])
