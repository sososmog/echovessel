"""Smoke tests for the corpus loader.

Verify the real yaml file parses and every required ground_truth category
has at least its tracker-mandated minimum count. If these tests fail, the
corpus got reshaped without updating the loader — flag to main thread.
"""

from __future__ import annotations

from tests.eval.corpus_loader import load_corpus


def test_corpus_loads_from_real_yaml():
    corpus = load_corpus()
    assert corpus.name == "mvp-baseline-v0.1"
    assert corpus.total_days == 14
    assert corpus.channel_id == "test"


def test_corpus_ground_truth_minimum_counts():
    corpus = load_corpus()
    gt = corpus.ground_truth
    assert len(gt.facts) >= 10
    assert len(gt.peaks) >= 6
    assert len(gt.identity_bearing) >= 4
    assert len(gt.turning_points) >= 3
    assert len(gt.red_herrings) >= 8
    assert len(gt.deletion_targets) >= 4


def test_corpus_days_cover_1_to_14_without_gaps():
    corpus = load_corpus()
    day_nums = sorted(d.day for d in corpus.days)
    assert day_nums == list(range(1, 15))


def test_every_session_has_channel_test():
    corpus = load_corpus()
    for day in corpus.days:
        for session in day.sessions:
            assert session.channel_id == "test", (
                f"Session {session.session_id} has channel_id {session.channel_id!r}, "
                "expected 'test'. Per tracker §7.1 all sessions must be on the test channel."
            )


def test_day_3_has_shock_peak():
    corpus = load_corpus()
    day_3_peaks = [
        p for p in corpus.ground_truth.peaks if p.day == 3
    ]
    assert day_3_peaks, "Day 3 must have at least one emotional peak"
    assert any(p.impact <= -8 for p in day_3_peaks), (
        "Day 3 peak must trigger SHOCK (impact <= -8); the corpus is Thread E "
        "frozen delivery and this guarantee is load-bearing for the eval"
    )


def test_day_9_has_positive_peak():
    corpus = load_corpus()
    day_9_peaks = [
        p for p in corpus.ground_truth.peaks if p.day == 9
    ]
    assert day_9_peaks
    assert any(p.impact >= 7 for p in day_9_peaks)


def test_golden_questions_have_all_four_types():
    corpus = load_corpus()
    factual = [q for q in corpus.golden_questions if q.type == "factual_recall"]
    peak = [
        q for q in corpus.golden_questions if q.type == "emotional_peak_recall"
    ]
    intrusion = [q for q in corpus.golden_questions if q.intrusion_check]
    deletion = [q for q in corpus.golden_questions if q.deletion_check]
    assert len(factual) >= 3
    assert len(peak) >= 3
    assert len(intrusion) >= 3
    assert len(deletion) >= 3
