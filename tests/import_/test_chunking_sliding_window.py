"""Long paragraphs are sliced with a 1500 / 500 sliding window."""

from __future__ import annotations

from echovessel.import_.chunking import (
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
    WINDOW_CHARS,
    chunk_text,
)


def test_long_paragraph_split_into_windows():
    long_para = "x" * 3200  # > MAX_CHUNK_CHARS (2000)
    chunks = chunk_text(long_para)
    assert len(chunks) >= 2
    assert all(len(c.content) <= WINDOW_CHARS for c in chunks)
    # Every chunk except the last should be exactly WINDOW_CHARS long.
    for c in chunks[:-1]:
        assert len(c.content) == WINDOW_CHARS


def test_window_overlap_consistency():
    # Verify adjacent chunks overlap by OVERLAP_CHARS.
    body = "".join(chr(ord("a") + (i % 26)) for i in range(3400))
    chunks = chunk_text(body)
    assert len(chunks) >= 2
    stride = WINDOW_CHARS - OVERLAP_CHARS
    # chunk[0] covers [0, WINDOW_CHARS), chunk[1] covers [stride, stride+WINDOW_CHARS)
    assert chunks[0].content == body[:WINDOW_CHARS]
    assert chunks[1].content.startswith(body[stride : stride + 50])


def test_short_paragraph_untouched():
    body = "short enough"
    chunks = chunk_text(body)
    assert len(chunks) == 1
    assert chunks[0].content == body
    assert len(body) <= MAX_CHUNK_CHARS
