"""Tests for the emr_dummy.debugging remote-debugger hook."""

import pytest

from emr_dummy.debugging import attach_remote_debugger


class TestAttachRemoteDebugger:
    """Tests for the attach_remote_debugger hook."""

    def test_noop_when_debug_host_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Hook returns silently when DEBUG_HOST is not set."""
        monkeypatch.delenv("DEBUG_HOST", raising=False)
        assert attach_remote_debugger() is None

    def test_pydevd_failure_raises_runtime_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RuntimeError raised when pydevd is missing or unreachable."""
        monkeypatch.setenv("DEBUG_HOST", "127.0.0.1")
        monkeypatch.setenv("DEBUG_PORT", "1")
        monkeypatch.setenv("DEBUGGER", "pydevd")
        with pytest.raises(RuntimeError):
            attach_remote_debugger()

    def test_debugpy_failure_raises_runtime_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RuntimeError raised when debugpy is missing or unreachable."""
        monkeypatch.setenv("DEBUG_HOST", "127.0.0.1")
        monkeypatch.setenv("DEBUG_PORT", "1")
        monkeypatch.setenv("DEBUGGER", "debugpy")
        with pytest.raises(RuntimeError):
            attach_remote_debugger()
