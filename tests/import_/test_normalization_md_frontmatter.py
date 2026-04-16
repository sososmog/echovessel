"""Markdown with YAML-style front-matter is folded into the body."""

from __future__ import annotations

from echovessel.import_.normalization import normalize_bytes

FRONTMATTER_DOC = """\
---
title: Alan's Diary
date: 2024-06-14
---

Today I finally saw Mochi's favorite window again.
"""


def test_frontmatter_merged_into_body():
    raw = FRONTMATTER_DOC.encode()
    out = normalize_bytes(raw, suffix=".md")
    # front-matter lines become plain "key: value" metadata.
    assert "title: Alan's Diary" in out
    assert "date: 2024-06-14" in out
    # body content survives
    assert "Today I finally saw Mochi's favorite window again." in out
    # the raw --- fences should be gone
    assert "---" not in out


def test_plain_markdown_passes_through():
    raw = b"# Heading\n\nBody text.\n"
    out = normalize_bytes(raw, suffix=".md")
    assert out.startswith("# Heading")
