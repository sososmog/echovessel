"""Non-UTF-8 bytes raise NormalizationError."""

from __future__ import annotations

import pytest

from echovessel.import_.errors import NormalizationError
from echovessel.import_.normalization import normalize_bytes


def test_latin1_bytes_reject():
    # 0xff is valid latin-1 but an invalid UTF-8 start byte.
    raw = b"good start \xff\xfe bad tail"
    with pytest.raises(NormalizationError):
        normalize_bytes(raw, suffix=".txt")


def test_invalid_json_rejected():
    raw = b"{ not valid json"
    with pytest.raises(NormalizationError):
        normalize_bytes(raw, suffix=".json")
