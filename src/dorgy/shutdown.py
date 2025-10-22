"""Graceful shutdown helpers shared across CLI entry points and pipelines."""

from __future__ import annotations

import os
import signal
import sys
import threading
from contextlib import AbstractContextManager
from types import FrameType
from typing import Callable, Literal


class ShutdownRequested(RuntimeError):
    """Raised when a graceful shutdown has been requested."""


_shutdown_event = threading.Event()
_lock = threading.Lock()
_signal_counts: dict[int, int] = {}


def shutdown_requested() -> bool:
    """Return whether a shutdown has been requested."""

    return _shutdown_event.is_set()


def check_for_shutdown(message: str | None = None) -> None:
    """Raise :class:`ShutdownRequested` when a shutdown has been requested."""

    if shutdown_requested():
        raise ShutdownRequested(message or "Shutdown requested.")


def wait_for_shutdown(timeout: float | None = None) -> bool:
    """Block until a shutdown is requested or the timeout elapses."""

    return _shutdown_event.wait(timeout)


def request_shutdown() -> None:
    """Programmatically request a graceful shutdown."""

    _shutdown_event.set()


def reset_shutdown_state() -> None:
    """Reset the shutdown event and counters (primarily for tests)."""

    _shutdown_event.clear()
    _signal_counts.clear()


class ShutdownManager(AbstractContextManager["ShutdownManager"]):
    """Context manager that installs signal handlers to request shutdown."""

    def __init__(self) -> None:
        self._original_handlers: dict[
            int, Callable[[int, FrameType | None], None] | int | None
        ] = {}

    # ------------------------------------------------------------------ #
    # Context management                                                 #
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "ShutdownManager":
        self._install_handlers()
        reset_shutdown_state()
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        self._restore_handlers()
        reset_shutdown_state()
        return False

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _install_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                previous = signal.getsignal(signum)
            except (AttributeError, ValueError):
                continue
            self._original_handlers[signum] = previous
            signal.signal(signum, self._handle_signal)

    def _restore_handlers(self) -> None:
        for signum, handler in self._original_handlers.items():
            try:
                signal.signal(signum, handler)
            except (AttributeError, ValueError):
                continue
        self._original_handlers.clear()

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        with _lock:
            count = _signal_counts.get(signum, 0) + 1
            _signal_counts[signum] = count
            if not _shutdown_event.is_set():
                _shutdown_event.set()
        if count == 1:
            self._announce_shutdown(signum)
            raise KeyboardInterrupt

        # Escalate on repeated attempts by restoring the original handler and re-sending.
        self._restore_and_exit(signum)

    def _announce_shutdown(self, signum: int) -> None:
        try:
            signal_name = signal.Signals(signum).name
        except ValueError:
            signal_name = str(signum)
        sys.stderr.write(
            f"\nReceived {signal_name}. Attempting graceful shutdown "
            "(press Ctrl+C again to terminate immediately).\n"
        )
        sys.stderr.flush()

    def _restore_and_exit(self, signum: int) -> None:
        handler = self._original_handlers.get(signum, signal.SIG_DFL)
        if handler is None:
            handler = signal.SIG_DFL
        try:
            signal.signal(signum, handler)
        except (AttributeError, ValueError):
            handler = signal.SIG_DFL
        os.kill(os.getpid(), signum)


shutdown_manager = ShutdownManager()

__all__ = [
    "ShutdownRequested",
    "ShutdownManager",
    "check_for_shutdown",
    "reset_shutdown_state",
    "request_shutdown",
    "shutdown_manager",
    "shutdown_requested",
    "wait_for_shutdown",
]
