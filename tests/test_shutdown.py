from __future__ import annotations

import pytest

from dorgy.shutdown import (
    ShutdownManager,
    ShutdownRequested,
    check_for_shutdown,
    request_shutdown,
    reset_shutdown_state,
    shutdown_requested,
)


def test_check_for_shutdown_raises_when_requested() -> None:
    """check_for_shutdown should raise once a shutdown is requested."""

    reset_shutdown_state()
    request_shutdown()
    with pytest.raises(ShutdownRequested):
        check_for_shutdown()
    reset_shutdown_state()


def test_shutdown_manager_resets_state_on_exit() -> None:
    """ShutdownManager should clear state after exiting the context."""

    reset_shutdown_state()
    with ShutdownManager():
        assert shutdown_requested() is False
        request_shutdown()
        assert shutdown_requested() is True
    assert shutdown_requested() is False
