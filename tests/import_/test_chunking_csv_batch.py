"""CSV-looking text is batched into multi-row chunks."""

from __future__ import annotations

from echovessel.import_.chunking import CSV_BATCH, chunk_text


def test_csv_rows_batched():
    rows = [f"row{i},value{i},note{i}" for i in range(20)]
    text = "\n".join(rows)
    chunks = chunk_text(text)
    # 20 rows / batch of CSV_BATCH ≈ ceil(20/8) = 3 chunks.
    expected_chunks = -(-20 // CSV_BATCH)
    assert len(chunks) == expected_chunks
    # First chunk contains the first CSV_BATCH rows
    assert chunks[0].content.count("\n") == CSV_BATCH - 1
    assert "row0,value0,note0" in chunks[0].content
    assert f"row{CSV_BATCH - 1}" in chunks[0].content
    # The 2nd chunk starts from row index CSV_BATCH
    assert f"row{CSV_BATCH},value{CSV_BATCH}" in chunks[1].content


def test_mixed_paragraphs_not_treated_as_csv():
    # Blank lines short-circuit the CSV heuristic.
    text = "a, b, c\n\nnot csv here"
    chunks = chunk_text(text)
    # Paragraph split, not CSV batching.
    assert len(chunks) == 2
    assert chunks[0].content == "a, b, c"
    assert chunks[1].content == "not csv here"
