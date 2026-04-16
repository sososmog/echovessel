"""Metric computation for the MVP baseline eval.

Four pure functions, one per MVP core indicator. Each takes the immutable
Corpus + ScenarioResult and returns a MetricResult. No side effects, no
DB access, no ORM — everything operates on the dataclasses the scenario
runner already materialized.

Definitions strictly follow docs/memory/03-memory-eval.md §3.1 / §3.2 / §3.4
/ §3.6. Do not redesign them here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tests.eval.corpus_loader import Corpus
from tests.eval.fixtures import KEYWORD_AXES
from tests.eval.llm_stub_recordings import (
    DELETION_CONTENT_KEYWORDS,
    FACT_KEYWORD_MATCHERS,
    PEAK_KEYWORD_MATCHERS,
    description_covers,
)
from tests.eval.scenario import GoldenResult, RetrievedMemory, ScenarioResult

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class QuestionBreakdown:
    """Per-question detail for the Factual Recall / Peak Recall reports."""

    question_id: str
    question_text: str
    expected_ids: list[str]
    covered_ids: list[str]
    missing_ids: list[str]
    top_descriptions: list[str]
    precision: float
    recall: float
    f1: float


@dataclass(slots=True)
class FactualRecallResult:
    f1: float
    avg_precision: float
    avg_recall: float
    num_questions: int
    # Diagnostic: per-question IR-style precision averaged across questions.
    # Not used for the MVP pass/fail decision — the primary f1 above uses the
    # question-level correctness rate per eval doc §3.1.
    ir_avg_precision: float = 0.0
    ir_avg_recall: float = 0.0
    ir_avg_f1: float = 0.0
    per_question: list[QuestionBreakdown] = field(default_factory=list)


@dataclass(slots=True)
class PeakEntry:
    peak_id: str
    day: int
    session: str
    impact: int
    covered: bool
    cover_description: str | None


@dataclass(slots=True)
class PeakRetentionResult:
    rate: float
    total: int
    covered: int
    per_peak: list[PeakEntry] = field(default_factory=list)


@dataclass(slots=True)
class OverRecallEntry:
    source_id: str
    kind: str  # 'extraction' | 'intrusion'
    description: str
    fp: bool
    offending_memory: str | None = None


@dataclass(slots=True)
class OverRecallResult:
    fp_rate: float
    total_samples: int
    fp_count: int
    extraction_fp: int
    intrusion_fp: int
    per_sample: list[OverRecallEntry] = field(default_factory=list)


@dataclass(slots=True)
class DeletionEntry:
    target_id: str
    question_id: str | None
    deleted: bool
    compliant: bool
    leaked_descriptions: list[str]


@dataclass(slots=True)
class DeletionComplianceResult:
    rate: float
    total: int
    compliant: int
    per_target: list[DeletionEntry] = field(default_factory=list)


@dataclass(slots=True)
class AllMetrics:
    factual_recall: FactualRecallResult
    peak_retention: PeakRetentionResult
    over_recall: OverRecallResult
    deletion_compliance: DeletionComplianceResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory_covers_fact(memory_description: str, fact_id: str) -> bool:
    """Strict match — used for Recall. A memory *covers* a fact iff its
    description contains the canonical keywords that uniquely identify the
    fact (see FACT_KEYWORD_MATCHERS)."""
    matchers = FACT_KEYWORD_MATCHERS.get(fact_id)
    if not matchers:
        return False
    return description_covers(memory_description, matchers)


def _axes_for_matchers(matchers: tuple[str, ...]) -> set[int]:
    """Which KEYWORD_AXES axes do these matcher strings live on?"""
    axes: set[int] = set()
    for kw in matchers:
        axis = KEYWORD_AXES.get(kw.lower())
        if axis is not None:
            axes.add(axis)
    return axes


def _memory_axes(description: str) -> set[int]:
    """Which KEYWORD_AXES axes does this memory description touch?"""
    axes: set[int] = set()
    lowered = description.lower()
    for kw, axis in KEYWORD_AXES.items():
        if kw in lowered:
            axes.add(axis)
    return axes


def _memory_is_relevant_to_facts(
    memory_description: str, expected_fact_ids: list[str]
) -> bool:
    """Loose match — used for Precision. A memory is *relevant* to a set of
    expected facts iff it shares a semantic axis with any of them, which is
    the MVP stand-in for "an LLM judge would say this memory is on-topic".

    Rationale: §3.1's Precision is "fraction of top-K that is 'relevant'".
    Without a lenient topic-level definition, Precision caps at 1/K for any
    question with a single expected fact, which makes F1 math impossible.
    The axis overlap check approximates what a real judge would call
    'on-topic' without hand-writing LLM verdicts for every retrieval."""
    expected_axes: set[int] = set()
    for fid in expected_fact_ids:
        expected_axes |= _axes_for_matchers(FACT_KEYWORD_MATCHERS.get(fid, ()))
    if not expected_axes:
        return False
    return bool(expected_axes & _memory_axes(memory_description))


def _memory_covers_peak(memory_description: str, peak_id: str) -> bool:
    matchers = PEAK_KEYWORD_MATCHERS.get(peak_id)
    if not matchers:
        return False
    return description_covers(memory_description, matchers)


def _memory_leaks_deletion(memory_description: str, deletion_id: str) -> bool:
    matchers = DELETION_CONTENT_KEYWORDS.get(deletion_id)
    if not matchers:
        return False
    return description_covers(memory_description, matchers)


def _any_peak_in_memories(
    memories: list[RetrievedMemory],
) -> tuple[bool, str | None]:
    """True if any retrieved memory covers any peak id (by keyword). Also
    returns the offending description for reporting."""
    for m in memories:
        for pid in PEAK_KEYWORD_MATCHERS:
            if _memory_covers_peak(m.description, pid):
                return True, m.description
        # Additional heuristic: very high-impact events count as peaks
        # even when the keyword matcher misses. Guards against extraction
        # drift.
        if abs(m.emotional_impact) >= 7:
            return True, m.description
    return False, None


# ---------------------------------------------------------------------------
# 3.1 · Factual Recall F1
# ---------------------------------------------------------------------------


def factual_recall_f1(
    corpus: Corpus, result: ScenarioResult
) -> FactualRecallResult:
    """Compute Factual Recall per docs/memory/03-memory-eval.md §3.1.

    §3.1 is phrased at the aggregate level:

        Precision = 回答正确的问题数 / 被召回事实的问题数
        Recall    = 回答正确的问题数 / 总问题数
        F1        = 调和平均

    Where "回答正确的问题" = a question whose expected facts are covered by
    the retrieved top-K. The primary F1 reported to MVP pass/fail uses this
    aggregate definition.

    We also compute the §5.1 per-question IR-style breakdown (K=10 with an
    on-topic judge) as diagnostic fields, because main thread may want both
    views when reading the report.
    """
    per: list[QuestionBreakdown] = []
    sum_p = sum_r = sum_f = 0.0  # IR-style averages across questions

    for gr in result.golden_results:
        gq = gr.question
        if gq.type != "factual_recall":
            continue

        expected = list(gq.expected_facts)
        top = gr.retrieved
        top_descs = [m.description for m in top]
        k = len(top)

        if not expected:
            # A factual_recall question with an empty expected set degenerates:
            # treat as a sanity check and score 1.0 iff retrieval returned
            # anything. Never used in this corpus but be defensive.
            p = r = f = 1.0 if top else 0.0
            per.append(
                QuestionBreakdown(
                    question_id=gq.id,
                    question_text=gq.question,
                    expected_ids=expected,
                    covered_ids=[],
                    missing_ids=[],
                    top_descriptions=top_descs,
                    precision=p,
                    recall=r,
                    f1=f,
                )
            )
            sum_p += p
            sum_r += r
            sum_f += f
            continue

        covered: list[str] = []
        missing: list[str] = []
        for fid in expected:
            if any(_memory_covers_fact(d, fid) for d in top_descs):
                covered.append(fid)
            else:
                missing.append(fid)

        relevant_retrieved = sum(
            1
            for d in top_descs
            if _memory_is_relevant_to_facts(d, expected)
        )

        precision = relevant_retrieved / k if k > 0 else 0.0
        recall = len(covered) / len(expected) if expected else 0.0
        f1 = (
            0.0
            if precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )

        per.append(
            QuestionBreakdown(
                question_id=gq.id,
                question_text=gq.question,
                expected_ids=expected,
                covered_ids=covered,
                missing_ids=missing,
                top_descriptions=top_descs,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
        sum_p += precision
        sum_r += recall
        sum_f += f1

    n = len(per)
    if n == 0:
        return FactualRecallResult(
            f1=0.0, avg_precision=0.0, avg_recall=0.0, num_questions=0
        )

    # --- Aggregate §3.1 computation ---------------------------------
    # A question is "correct" iff every expected fact appears in top-K.
    correct = sum(1 for q in per if not q.missing_ids)
    # "被召回事实的问题数" — questions that returned any relevant memory.
    # With top_k=10 and a non-empty corpus, retrieve always returns
    # something, so this equals n. We still compute it explicitly for
    # future-proofing against degenerate empty-retrieval cases.
    retrieved_any = sum(1 for q in per if q.top_descriptions)
    aggregate_precision = correct / retrieved_any if retrieved_any else 0.0
    aggregate_recall = correct / n
    if aggregate_precision + aggregate_recall == 0:
        aggregate_f1 = 0.0
    else:
        aggregate_f1 = (
            2
            * aggregate_precision
            * aggregate_recall
            / (aggregate_precision + aggregate_recall)
        )

    return FactualRecallResult(
        f1=round(aggregate_f1, 4),
        avg_precision=round(aggregate_precision, 4),
        avg_recall=round(aggregate_recall, 4),
        num_questions=n,
        ir_avg_precision=round(sum_p / n, 4),
        ir_avg_recall=round(sum_r / n, 4),
        ir_avg_f1=round(sum_f / n, 4),
        per_question=per,
    )


# ---------------------------------------------------------------------------
# 3.2 · Emotional Peak Retention
# ---------------------------------------------------------------------------


def emotional_peak_retention(
    corpus: Corpus, result: ScenarioResult
) -> PeakRetentionResult:
    """For each ground_truth peak, was it extracted?

    The §3.2 definition has two sub-rates (抽取率 + 召回率). MVP target is
    the extraction rate >= 0.95 — "情绪峰值绝不能漏抽". A peak is considered
    extracted iff its gt_id appears in `result.gt_to_node`, which the
    scenario runner populates by zipping the canned extraction list with the
    ConceptNodes consolidate_session created. That mapping is the ground
    truth of "did extraction put this peak into L3".
    """
    per: list[PeakEntry] = []
    covered = 0

    for peak in corpus.ground_truth.peaks:
        extracted = peak.id in result.gt_to_node
        per.append(
            PeakEntry(
                peak_id=peak.id,
                day=peak.day,
                session=peak.session,
                impact=peak.impact,
                covered=extracted,
                cover_description=None,
            )
        )
        if extracted:
            covered += 1

    total = len(per)
    rate = round(covered / total, 4) if total else 0.0
    return PeakRetentionResult(
        rate=rate, total=total, covered=covered, per_peak=per
    )


# ---------------------------------------------------------------------------
# 3.4 · Over-recall FP Rate
# ---------------------------------------------------------------------------


def over_recall_fp_rate(
    corpus: Corpus, result: ScenarioResult
) -> OverRecallResult:
    """Count two kinds of false positives and combine into a single rate.

    Part A (extraction): any red_herring whose source session produced an
    event that covers the herring's content. In the MVP stub the canned
    extraction table never emits herring events, so this should be 0 — but
    we verify rather than assume, so future canned-table edits can't lie.

    Part B (intrusion): any intrusion_check golden question whose top-K
    contains an emotional peak event. This is the behavioural arm of the
    test — does retrieve surface sad memories when the user asks about
    the weather?
    """
    entries: list[OverRecallEntry] = []
    extraction_fp = 0
    intrusion_fp = 0

    # --- Part A --------------------------------------------------------
    extraction_by_session = {
        er.corpus_session_id: er for er in result.extractions
    }

    for herring in corpus.ground_truth.red_herrings:
        er = extraction_by_session.get(herring.session)
        fp = False
        description: str | None = None
        if er is not None:
            # Any canned entry whose description mentions herring content?
            from tests.eval.llm_stub_recordings import SESSION_EXTRACTIONS
            canned = SESSION_EXTRACTIONS.get(herring.session, [])
            for entry in canned:
                if description_covers(
                    entry["description"], _herring_keywords(herring.content)
                ):
                    fp = True
                    description = entry["description"]
                    break
        if fp:
            extraction_fp += 1
        entries.append(
            OverRecallEntry(
                source_id=herring.id,
                kind="extraction",
                description=herring.content,
                fp=fp,
                offending_memory=description,
            )
        )

    # --- Part B --------------------------------------------------------
    for gr in result.golden_results:
        gq = gr.question
        if not gq.intrusion_check:
            continue
        leaked, who = _any_peak_in_memories(gr.retrieved)
        if leaked:
            intrusion_fp += 1
        entries.append(
            OverRecallEntry(
                source_id=gq.id,
                kind="intrusion",
                description=gq.question,
                fp=leaked,
                offending_memory=who,
            )
        )

    total = len(corpus.ground_truth.red_herrings) + sum(
        1 for g in result.golden_results if g.question.intrusion_check
    )
    fp_count = extraction_fp + intrusion_fp
    rate = round(fp_count / total, 4) if total else 0.0
    return OverRecallResult(
        fp_rate=rate,
        total_samples=total,
        fp_count=fp_count,
        extraction_fp=extraction_fp,
        intrusion_fp=intrusion_fp,
        per_sample=entries,
    )


def _herring_keywords(content: str) -> tuple[str, ...]:
    """Cheap keyword extractor for red herring content; we use the words
    likely to appear verbatim in an extraction description if it were ever
    (incorrectly) generated."""
    lowered = content.lower()
    seeds = (
        "三明治",
        "便利店",
        "地铁",
        "晚点",
        "牙线",
        "天气",
        "下雨",
        "空调",
        "usb-c",
        "快递",
        "小狗",
        "podcast",
        "海盐",
        "拿铁",
    )
    return tuple(s for s in seeds if s in lowered)


# ---------------------------------------------------------------------------
# 3.6 · Deletion Compliance
# ---------------------------------------------------------------------------


def deletion_compliance(
    corpus: Corpus, result: ScenarioResult
) -> DeletionComplianceResult:
    """For each deletion target, verify zero leak in the post-deletion
    golden question's retrieved top-K.

    Matching deletion targets to their verification question uses the
    `deleted_target` field on each deletion_check golden question, which
    Thread E tagged explicitly.
    """
    # Build target_id → golden question lookup
    verify_by_target: dict[str, GoldenResult] = {}
    for gr in result.golden_results:
        if gr.question.deletion_check and gr.question.deleted_target:
            verify_by_target[gr.question.deleted_target] = gr

    per: list[DeletionEntry] = []
    compliant = 0
    for target in corpus.ground_truth.deletion_targets:
        deleted = target.id in result.deletions_applied
        gr = verify_by_target.get(target.id)
        leaked: list[str] = []
        if gr is not None:
            for m in gr.retrieved:
                if _memory_leaks_deletion(m.description, target.id):
                    leaked.append(m.description)
        is_compliant = deleted and not leaked and gr is not None
        # A missing verification question is a compliance hole, even if the
        # delete itself succeeded — without a checker we can't claim 1.0.
        if is_compliant:
            compliant += 1
        per.append(
            DeletionEntry(
                target_id=target.id,
                question_id=gr.question.id if gr else None,
                deleted=deleted,
                compliant=is_compliant,
                leaked_descriptions=leaked,
            )
        )

    total = len(per)
    rate = round(compliant / total, 4) if total else 0.0
    return DeletionComplianceResult(
        rate=rate, total=total, compliant=compliant, per_target=per
    )


# ---------------------------------------------------------------------------
# Bundler
# ---------------------------------------------------------------------------


def compute_all(corpus: Corpus, result: ScenarioResult) -> AllMetrics:
    return AllMetrics(
        factual_recall=factual_recall_f1(corpus, result),
        peak_retention=emotional_peak_retention(corpus, result),
        over_recall=over_recall_fp_rate(corpus, result),
        deletion_compliance=deletion_compliance(corpus, result),
    )
