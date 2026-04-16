"""End-to-end mini scenario test.

Runs the full 14-day baseline replay once and asserts the top-level
invariants:

    - Scenario completes without raising
    - All 4 deletions applied successfully
    - All 6 peaks are extracted
    - At least one golden question captured per required type

This is the smallest test that still exercises the full
ingest → consolidate → retrieve → forget loop. It's slower than the unit
tests (~1s) but cheaper than a live LLM run.
"""

from __future__ import annotations

from tests.eval.corpus_loader import load_corpus
from tests.eval.metrics import compute_all
from tests.eval.scenario import run_scenario


def test_scenario_runs_end_to_end_on_real_corpus():
    corpus = load_corpus()
    result = run_scenario(corpus)

    # 36 corpus sessions → 36 extraction records
    assert len(result.extractions) == 36

    # All 6 peaks must have been extracted and tracked by gt_id
    for peak in corpus.ground_truth.peaks:
        assert peak.id in result.gt_to_node, (
            f"Peak {peak.id} not present in gt_to_node map — stub extraction "
            "is mis-aligned with the corpus"
        )

    # All 4 deletions must have been applied
    assert sorted(result.deletions_applied) == [
        "del_001",
        "del_002",
        "del_003",
        "del_004",
    ]
    assert result.deletions_missing == []

    # Golden questions captured (19 — gq_020 is filtered out as sanity marker)
    assert len(result.golden_results) == 19

    # Metrics compute without error and yield the deterministic numbers
    m = compute_all(corpus, result)
    assert m.peak_retention.rate == 1.0
    assert m.deletion_compliance.rate == 1.0
    assert m.factual_recall.num_questions == 7


def test_scenario_reproducibility_within_single_process():
    """Two back-to-back runs return bit-for-bit identical metric numbers."""
    corpus = load_corpus()
    r1 = run_scenario(corpus)
    r2 = run_scenario(corpus)
    m1 = compute_all(corpus, r1)
    m2 = compute_all(corpus, r2)

    assert m1.factual_recall.f1 == m2.factual_recall.f1
    assert m1.peak_retention.rate == m2.peak_retention.rate
    assert m1.over_recall.fp_rate == m2.over_recall.fp_rate
    assert m1.deletion_compliance.rate == m2.deletion_compliance.rate
