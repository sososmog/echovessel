"""Tests for echovessel.voice.errors hierarchy."""

from __future__ import annotations

import pytest

from echovessel.voice.errors import (
    VoiceBudgetError,
    VoiceError,
    VoicePermanentError,
    VoiceTransientError,
)


def test_voice_error_is_base():
    assert issubclass(VoiceTransientError, VoiceError)
    assert issubclass(VoicePermanentError, VoiceError)
    assert issubclass(VoiceBudgetError, VoiceError)


def test_transient_and_permanent_are_siblings():
    assert not issubclass(VoiceTransientError, VoicePermanentError)
    assert not issubclass(VoicePermanentError, VoiceTransientError)


def test_budget_is_a_permanent_error():
    """Budget errors should not be retried — they're a subtype of permanent."""
    assert issubclass(VoiceBudgetError, VoicePermanentError)


def test_error_can_be_raised_and_caught():
    with pytest.raises(VoiceError):
        raise VoiceTransientError("test transient")

    with pytest.raises(VoicePermanentError):
        raise VoicePermanentError("test permanent")

    with pytest.raises(VoicePermanentError):
        # Budget is also a permanent — the catch pattern in runtime is
        # `except VoicePermanentError` and it must catch budget too.
        raise VoiceBudgetError("quota")

    with pytest.raises(VoiceError):
        raise VoiceBudgetError("quota")


def test_error_messages_preserved():
    try:
        raise VoiceTransientError("server 503")
    except VoiceTransientError as e:
        assert "server 503" in str(e)


def test_error_chaining():
    """`raise ... from e` must work for wrapping SDK exceptions."""
    try:
        try:
            raise ValueError("sdk failure")
        except ValueError as inner:
            raise VoiceTransientError("wrapped") from inner
    except VoiceTransientError as e:
        assert isinstance(e.__cause__, ValueError)
        assert "sdk failure" in str(e.__cause__)
