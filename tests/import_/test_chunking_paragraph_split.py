"""Paragraph-based chunking for short text."""

from __future__ import annotations

from echovessel.import_.chunking import chunk_text


def test_single_short_paragraph_one_chunk():
    chunks = chunk_text("A short sentence.", source_label="test")
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1
    assert chunks[0].content == "A short sentence."
    assert chunks[0].source_label == "test"


def test_two_paragraphs_split_on_blank_line():
    text = "First paragraph about Mochi.\n\nSecond paragraph about Alan."
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert "Mochi" in chunks[0].content
    assert "Alan" in chunks[1].content
    assert chunks[0].total_chunks == 2
    assert chunks[1].total_chunks == 2


def test_whitespace_only_returns_empty_list():
    assert chunk_text("   \n\n\n  ") == []
    assert chunk_text("") == []
