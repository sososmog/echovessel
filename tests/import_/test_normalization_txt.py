"""UTF-8 text passes through normalization unchanged."""

from __future__ import annotations

from echovessel.import_.normalization import normalize_bytes


def test_utf8_txt_roundtrip():
    raw = "今天的天气很好\nToday was a good day.\n".encode()
    out = normalize_bytes(raw, suffix=".txt")
    assert "今天的天气很好" in out
    assert "Today was a good day." in out


def test_unknown_suffix_falls_through_as_utf8():
    raw = b"plain content with no extension"
    out = normalize_bytes(raw, suffix="")
    assert out == "plain content with no extension"
