"""Pure-function tests for tests/eval/metrics.py.

These build tiny synthetic Corpus + ScenarioResult fixtures so they can
verify each metric's arithmetic without running the full 14-day replay.
"""

from __future__ import annotations

from tests.eval.corpus_loader import (
    Corpus,
    DeletionTarget,
    EmotionalPeak,
    Fact,
    GoldenQuestion,
    GroundTruth,
    RedHerring,
)
from tests.eval.metrics import (
    deletion_compliance,
    emotional_peak_retention,
    factual_recall_f1,
    over_recall_fp_rate,
)
from tests.eval.scenario import (
    ExtractionRecord,
    GoldenResult,
    RetrievedMemory,
    ScenarioResult,
)


def _minimal_ground_truth(**overrides) -> GroundTruth:
    defaults = {
        "facts": (),
        "peaks": (),
        "identity_bearing": (),
        "turning_points": (),
        "red_herrings": (),
        "deletion_targets": (),
    }
    defaults.update(overrides)
    return GroundTruth(**defaults)


def _corpus(**gt_overrides) -> Corpus:
    return Corpus(
        name="test",
        version="0.0",
        total_days=1,
        channel_id="test",
        ground_truth=_minimal_ground_truth(**gt_overrides),
        days=(),
        golden_questions=(),
    )


def _mem(desc: str, impact: int = 0) -> RetrievedMemory:
    return RetrievedMemory(
        node_id=1,
        description=desc,
        emotional_impact=impact,
        emotion_tags=(),
        relational_tags=(),
        source_session_id=None,
        score=1.0,
    )


# ---------------------------------------------------------------------------
# Factual Recall
# ---------------------------------------------------------------------------


def test_factual_recall_question_hits_expected_fact():
    corpus = _corpus(
        facts=(Fact(id="fact_001", content="a cat", category="pet"),)
    )
    gq = GoldenQuestion(
        id="q1",
        day=1,
        session="s1",
        question="什么猫",
        type="factual_recall",
        expected_facts=("fact_001",),
    )
    result = ScenarioResult(
        gt_to_node={},
        golden_results=[
            GoldenResult(
                question=gq,
                retrieved=[
                    _mem("用户养了一只叫 Mochi 的橘猫"),
                    _mem("无关事件一"),
                    _mem("无关事件二"),
                ],
            )
        ],
    )
    m = factual_recall_f1(corpus, result)
    assert m.num_questions == 1
    assert m.f1 == 1.0  # aggregate: the single question is fully covered


def test_factual_recall_missing_expected_fact_scores_zero():
    corpus = _corpus(
        facts=(
            Fact(id="fact_001", content="a cat", category="pet"),
            Fact(id="fact_002", content="engineer", category="work"),
        )
    )
    gq = GoldenQuestion(
        id="q1",
        day=1,
        session="s1",
        question="做什么",
        type="factual_recall",
        expected_facts=("fact_002",),
    )
    result = ScenarioResult(
        gt_to_node={},
        golden_results=[
            GoldenResult(
                question=gq,
                retrieved=[_mem("用户养了一只叫 Mochi 的橘猫")],
            )
        ],
    )
    m = factual_recall_f1(corpus, result)
    assert m.f1 == 0.0


# ---------------------------------------------------------------------------
# Emotional Peak Retention
# ---------------------------------------------------------------------------


def test_peak_retention_counts_covered_peaks():
    corpus = _corpus(
        peaks=(
            EmotionalPeak(
                id="peak_001",
                day=3,
                session="s_003",
                impact=-9,
                content="父亲去世",
                emotion_tags=("grief",),
                relational_tags=("identity-bearing",),
                shock_trigger=True,
            ),
            EmotionalPeak(
                id="peak_004",
                day=9,
                session="s_009",
                impact=8,
                content="拿到 offer",
                emotion_tags=("joy",),
                relational_tags=("identity-bearing",),
                shock_trigger=True,
            ),
        )
    )
    result = ScenarioResult(
        gt_to_node={"peak_001": 1, "peak_004": 2},
        extractions=[
            ExtractionRecord(
                corpus_session_id="s_003",
                db_session_id="sess_x",
                gt_ids=["peak_001"],
                node_ids=[1],
            ),
            ExtractionRecord(
                corpus_session_id="s_009",
                db_session_id="sess_y",
                gt_ids=["peak_004"],
                node_ids=[2],
            ),
        ],
    )
    m = emotional_peak_retention(corpus, result)
    assert m.total == 2
    assert m.covered == 2
    assert m.rate == 1.0


def test_peak_retention_scores_partial_coverage():
    corpus = _corpus(
        peaks=(
            EmotionalPeak(
                id="peak_001",
                day=3,
                session="s_003",
                impact=-9,
                content="父亲去世",
                emotion_tags=(),
                relational_tags=(),
                shock_trigger=True,
            ),
            EmotionalPeak(
                id="peak_004",
                day=9,
                session="s_009",
                impact=8,
                content="拿到 offer",
                emotion_tags=(),
                relational_tags=(),
                shock_trigger=True,
            ),
        )
    )
    result = ScenarioResult(
        gt_to_node={"peak_001": 1},
        extractions=[
            ExtractionRecord(
                corpus_session_id="s_003",
                db_session_id="sess_x",
                gt_ids=["peak_001"],
                node_ids=[1],
            ),
        ],
    )
    m = emotional_peak_retention(corpus, result)
    assert m.total == 2
    assert m.covered == 1
    assert m.rate == 0.5


# ---------------------------------------------------------------------------
# Over-recall
# ---------------------------------------------------------------------------


def test_over_recall_clean_run_scores_zero():
    corpus = _corpus(
        red_herrings=(
            RedHerring(
                id="rh_001",
                day=2,
                session="s_002",
                content="便利店三明治",
            ),
        ),
    )
    # Intrusion question with no peaks in top-K
    gq = GoldenQuestion(
        id="q_intr",
        day=5,
        session="s_005",
        question="今天天气",
        type="over_recall_trap",
        intrusion_check=True,
    )
    result = ScenarioResult(
        gt_to_node={},
        extractions=[
            ExtractionRecord(
                corpus_session_id="s_002",
                db_session_id="sess_a",
                gt_ids=[],
                node_ids=[],
            )
        ],
        golden_results=[
            GoldenResult(
                question=gq,
                retrieved=[_mem("用户养了一只叫 Mochi 的橘猫", impact=2)],
            )
        ],
    )
    m = over_recall_fp_rate(corpus, result)
    assert m.fp_count == 0
    assert m.fp_rate == 0.0


def test_over_recall_flags_peak_intrusion():
    corpus = _corpus(
        red_herrings=(
            RedHerring(
                id="rh_001", day=2, session="s_002", content="便利店三明治"
            ),
        ),
    )
    gq = GoldenQuestion(
        id="q_intr",
        day=5,
        session="s_005",
        question="今天天气",
        type="over_recall_trap",
        intrusion_check=True,
    )
    result = ScenarioResult(
        gt_to_node={},
        extractions=[
            ExtractionRecord(
                corpus_session_id="s_002",
                db_session_id="sess_a",
                gt_ids=[],
                node_ids=[],
            )
        ],
        golden_results=[
            GoldenResult(
                question=gq,
                retrieved=[_mem("用户第一次对 persona 说起父亲两年前因病去世", impact=-9)],
            )
        ],
    )
    m = over_recall_fp_rate(corpus, result)
    # 1 intrusion + 0 extraction FP over 1 herring + 1 intrusion question = 0.5
    assert m.intrusion_fp == 1
    assert m.extraction_fp == 0
    assert m.fp_count == 1
    assert m.total_samples == 2
    assert m.fp_rate == 0.5


# ---------------------------------------------------------------------------
# Deletion Compliance
# ---------------------------------------------------------------------------


def test_deletion_compliance_clean_when_no_leaks():
    corpus = _corpus(
        deletion_targets=(
            DeletionTarget(
                id="del_001",
                planted_day=2,
                planted_session="s_002",
                content="橙子前任的回忆",
                delete_on_day=13,
            ),
        )
    )
    gq = GoldenQuestion(
        id="q_del",
        day=14,
        session="s_014",
        question="我提过的前任",
        type="deletion_check",
        deletion_check=True,
        deleted_target="del_001",
    )
    result = ScenarioResult(
        gt_to_node={},
        deletions_applied=["del_001"],
        golden_results=[
            GoldenResult(
                question=gq,
                retrieved=[_mem("用户养了一只叫 Mochi 的橘猫")],
            )
        ],
    )
    m = deletion_compliance(corpus, result)
    assert m.compliant == 1
    assert m.rate == 1.0


def test_deletion_compliance_flags_leak():
    corpus = _corpus(
        deletion_targets=(
            DeletionTarget(
                id="del_001",
                planted_day=2,
                planted_session="s_002",
                content="橙子前任",
                delete_on_day=13,
            ),
        )
    )
    gq = GoldenQuestion(
        id="q_del",
        day=14,
        session="s_014",
        question="前任",
        type="deletion_check",
        deletion_check=True,
        deleted_target="del_001",
    )
    result = ScenarioResult(
        gt_to_node={},
        deletions_applied=["del_001"],
        golden_results=[
            GoldenResult(
                question=gq,
                retrieved=[_mem("用户提到一位叫糖炒栗子的雨夜故事")],
            )
        ],
    )
    m = deletion_compliance(corpus, result)
    assert m.compliant == 0
    assert m.rate == 0.0
    assert m.per_target[0].leaked_descriptions  # at least one leak
