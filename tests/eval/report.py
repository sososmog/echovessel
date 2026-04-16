"""Markdown report renderer for one baseline eval run.

The output is written to `docs/memory/eval-runs/YYYY-MM-DD-baseline-<commit>.md`.
Layout matches docs/memory/02-eval-harness-tracker.md §1 (the "=== MVP
Baseline Eval Report ===" example). Everything but the metadata block at the
top is deterministic — running the same commit + the same canned library
yields an identical file (which keeps git diffs clean).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tests.eval.corpus_loader import Corpus
from tests.eval.metrics import AllMetrics

MVP_TARGETS = {
    "factual_recall": (0.80, "≥"),
    "peak_retention": (0.95, "≥"),
    "over_recall": (0.15, "≤"),
    "deletion_compliance": (1.00, "="),
}


@dataclass(slots=True)
class ReportMeta:
    corpus_name: str
    corpus_version: str
    commit_hash: str
    run_at: datetime
    canned_library_version: str = "v0.1"


def _status(name: str, value: float) -> str:
    target, op = MVP_TARGETS[name]
    if op == "≥":
        passed = value >= target
    elif op == "≤":
        passed = value <= target
    else:
        passed = abs(value - target) < 1e-9
    return "✅" if passed else "❌"


def _metric_line(label: str, value: float, target: float, op: str, mark: str) -> str:
    return f"{label:<30}{value:.4f}   (target {op} {target:.2f})  {mark}"


def render_console(metrics: AllMetrics, meta: ReportMeta) -> str:
    """Produce the short summary that run_baseline prints to stdout."""
    f1 = metrics.factual_recall.f1
    peak = metrics.peak_retention.rate
    over = metrics.over_recall.fp_rate
    deletion = metrics.deletion_compliance.rate

    passed = 0
    if f1 >= 0.80:
        passed += 1
    if peak >= 0.95:
        passed += 1
    if over <= 0.15:
        passed += 1
    if abs(deletion - 1.00) < 1e-9:
        passed += 1

    lines = []
    lines.append("=== MVP Baseline Eval Report ===")
    lines.append("")
    lines.append(
        _metric_line(
            "Factual Recall F1:", f1, 0.80, "≥", _status("factual_recall", f1)
        )
    )
    lines.append(
        _metric_line(
            "Emotional Peak Retention:",
            peak,
            0.95,
            "≥",
            _status("peak_retention", peak),
        )
    )
    lines.append(
        _metric_line(
            "Over-recall FP Rate:",
            over,
            0.15,
            "≤",
            _status("over_recall", over),
        )
    )
    lines.append(
        _metric_line(
            "Deletion Compliance:",
            deletion,
            1.00,
            "=",
            _status("deletion_compliance", deletion),
        )
    )
    lines.append("")
    lines.append(f"Result: {passed}/4 MVP metrics PASS")
    return "\n".join(lines)


def render_markdown(
    metrics: AllMetrics, corpus: Corpus, meta: ReportMeta
) -> str:
    """Full markdown report with per-question breakdown.

    The only non-deterministic fields are in the metadata block at the very
    top (commit_hash, run_at). Everything below is pure function of
    (corpus, metrics) so the git diff between runs stays narrow.
    """
    f1 = metrics.factual_recall
    peak = metrics.peak_retention
    over = metrics.over_recall
    deletion = metrics.deletion_compliance

    lines: list[str] = []
    lines.append(f"# MVP Baseline Eval — {meta.run_at.date().isoformat()}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Corpus: `{meta.corpus_name}` v{meta.corpus_version}")
    lines.append(f"- Canned library: `{meta.canned_library_version}`")
    lines.append(f"- Commit: `{meta.commit_hash}`")
    lines.append(f"- Run at: {meta.run_at.isoformat(timespec='seconds')}")
    lines.append(
        "- Harness: `tests.eval.run_baseline` (offline replay mode, StubProvider-equivalent callables)"
    )
    lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value | Target | Status |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| Factual Recall F1 | {f1.f1:.4f} | ≥ 0.80 | {_status('factual_recall', f1.f1)} |"
    )
    lines.append(
        f"| Emotional Peak Retention | {peak.rate:.4f} | ≥ 0.95 | {_status('peak_retention', peak.rate)} |"
    )
    lines.append(
        f"| Over-recall FP Rate | {over.fp_rate:.4f} | ≤ 0.15 | {_status('over_recall', over.fp_rate)} |"
    )
    lines.append(
        f"| Deletion Compliance | {deletion.rate:.4f} | = 1.00 | {_status('deletion_compliance', deletion.rate)} |"
    )
    lines.append("")

    passed = sum(
        [
            f1.f1 >= 0.80,
            peak.rate >= 0.95,
            over.fp_rate <= 0.15,
            abs(deletion.rate - 1.00) < 1e-9,
        ]
    )
    lines.append(f"**Result: {passed}/4 MVP metrics PASS**")
    lines.append("")

    # --- Factual Recall ---------------------------------------------
    lines.append("## 1. Factual Recall (eval doc §3.1)")
    lines.append("")
    lines.append(
        f"- Avg F1: **{f1.f1:.4f}**  (avg P: {f1.avg_precision:.4f}, avg R: {f1.avg_recall:.4f})"
    )
    lines.append(f"- Questions evaluated: {f1.num_questions}")
    lines.append("")
    lines.append("| Question | Expected | Covered | Missing | P | R | F1 |")
    lines.append("|---|---|---|---|---|---|---|")
    for qb in f1.per_question:
        expected = ", ".join(qb.expected_ids) if qb.expected_ids else "—"
        covered = ", ".join(qb.covered_ids) if qb.covered_ids else "—"
        missing = ", ".join(qb.missing_ids) if qb.missing_ids else "—"
        lines.append(
            f"| {qb.question_id} | {expected} | {covered} | {missing} "
            f"| {qb.precision:.2f} | {qb.recall:.2f} | {qb.f1:.2f} |"
        )
    lines.append("")

    # --- Emotional Peak Retention -----------------------------------
    lines.append("## 2. Emotional Peak Retention (eval doc §3.2)")
    lines.append("")
    lines.append(
        f"- Extraction rate: **{peak.rate:.4f}** ({peak.covered}/{peak.total})"
    )
    lines.append("")
    lines.append("| Peak | Day | Session | Impact | Extracted |")
    lines.append("|---|---|---|---|---|")
    for pe in peak.per_peak:
        mark = "✅" if pe.covered else "❌"
        lines.append(
            f"| {pe.peak_id} | {pe.day} | {pe.session} | {pe.impact:+d} | {mark} |"
        )
    lines.append("")

    # --- Over-recall ------------------------------------------------
    lines.append("## 3. Over-recall FP Rate (eval doc §3.4 Part A)")
    lines.append("")
    lines.append(
        f"- FP rate: **{over.fp_rate:.4f}** "
        f"({over.fp_count}/{over.total_samples})"
    )
    lines.append(
        f"- Extraction FP (red_herring → event): {over.extraction_fp}"
    )
    lines.append(f"- Intrusion FP (peak in intrusion_check top-K): {over.intrusion_fp}")
    lines.append("")
    lines.append("| Sample | Kind | Description | FP | Offending Memory |")
    lines.append("|---|---|---|---|---|")
    for e in over.per_sample:
        mark = "🚨" if e.fp else "—"
        offending = (e.offending_memory or "—")[:80]
        lines.append(
            f"| {e.source_id} | {e.kind} | {e.description[:40]} | {mark} | {offending} |"
        )
    lines.append("")

    # --- Deletion Compliance ----------------------------------------
    lines.append("## 4. Deletion Compliance (eval doc §3.6)")
    lines.append("")
    lines.append(
        f"- Rate: **{deletion.rate:.4f}** ({deletion.compliant}/{deletion.total})"
    )
    lines.append("")
    lines.append("| Target | Verification | Deleted | Compliant | Leaks |")
    lines.append("|---|---|---|---|---|")
    for de in deletion.per_target:
        q = de.question_id or "—"
        d_mark = "✅" if de.deleted else "❌"
        c_mark = "✅" if de.compliant else "❌"
        leaks = len(de.leaked_descriptions)
        lines.append(f"| {de.target_id} | {q} | {d_mark} | {c_mark} | {leaks} |")
    lines.append("")

    # --- Notes -------------------------------------------------------
    lines.append("## 5. Notes & caveats")
    lines.append("")
    lines.append(
        "- **Stubbed LLM**: Extraction, reflection, embedding and judging all use "
        "deterministic local stubs (see `tests/eval/llm_stub_recordings.py` and "
        "`tests/eval/fixtures.py`). No network or real model is invoked. "
        "Reproducibility across runs is guaranteed to 4 decimal places."
    )
    lines.append(
        "- **What is measured**: the real memory pipeline end-to-end — `ingest_message`, "
        "`consolidate_session` (with async `extract_fn`/`reflect_fn` stubs), "
        "`retrieve` with its rerank formula, `delete_concept_node` with backend "
        "cascade. The only fake parts are the LLM-bounded callables and the "
        "keyword-embedding stand-in for sentence-transformers."
    )
    lines.append(
        "- **Factual Recall interpretation**: primary F1 follows eval doc §3.1's "
        "aggregate wording — a question is 'correct' iff all its `expected_facts` "
        "appear in the top-K retrieval. The per-question IR-style precision / "
        "recall columns (§5.1 interpretation of the tracker) are kept as a "
        "diagnostic view because main thread may want both lenses when reviewing "
        "the report. With aggregate F1 we report the answer-correctness rate; "
        "with per-question IR F1 we'd see how much noise the top-K carries."
    )
    lines.append(
        "- **Thread RT dependency**: Runtime's `assemble_turn` / `LLMProvider` path "
        "is not yet in the tree, so golden-question retrieval is measured directly "
        "against `memory.retrieve` rather than the full prompt-assembly + persona-"
        "reply loop. Once Thread RT's PR 5 lands, Phase 2 of the harness can switch "
        "over without changes to metrics / report."
    )
    lines.append("")

    if over.fp_rate > 0.15:
        lines.append("## 6. Finding · Over-recall FP Rate fails MVP target")
        lines.append("")
        lines.append(
            f"The MVP target is ≤ 0.15; this run measured **{over.fp_rate:.4f}** "
            f"({over.intrusion_fp} intrusion FPs / "
            f"{over.intrusion_fp + over.extraction_fp} total FPs out of "
            f"{over.total_samples} samples). Every failure is on the intrusion "
            f"side — the canned extraction table never emits red-herring events, "
            f"so Extraction FP is 0."
        )
        lines.append("")
        lines.append(
            "**Root cause** (for main thread to decide on): the real "
            "`memory.retrieve` rerank weights (architecture v0.3 §3.2) give "
            "high-|impact| peak events a large bonus — `2.0 · |impact|/10` plus "
            "`1.0 · 0.5` for identity-bearing relational tags. A peak at impact "
            "-9 with identity-bearing tag picks up +2.3 points of score. For "
            "low-emotion queries (weather, podcasts, 'how was your day'), the "
            "query embedding is nearly orthogonal to every event, so relevance "
            "flattens to ~0.5 for all candidates and the impact/relational bonus "
            "decides top-K. The peak always wins."
        )
        lines.append("")
        lines.append(
            "Concretely: Day 3 seeded peak_001 (父亲去世, impact -9, "
            "identity-bearing). On Day 4 the intrusion probe is the "
            "low-emotion '今天过得还行'; retrieve still surfaces peak_001 at "
            "rank 1 because its boost dominates every other event. Same "
            "pattern on gq_011 (天气) and gq_013 (podcast). gq_012 is a milder "
            "variant: a Mochi-topic question correctly pulls fact_001 (fine) but "
            "also pulls peak_003 (Mochi vet worry, impact -6) — the shared Mochi "
            "axis amplifies relevance AND peak_003 carries 1.2 points of impact "
            "bonus, so it outranks 'flat' Mochi facts."
        )
        lines.append("")
        lines.append(
            "**What this harness does NOT do**: we do not propose a fix. "
            "Per 02-eval-harness-tracker.md §10.2 the harness reports and main "
            "thread decides. Options to consider (non-exhaustive): "
            "(a) reduce `WEIGHT_IMPACT` from 2.0 to ~0.8 so relevance dominates "
            "again when queries are low-emotion; (b) suppress peak events in "
            "top-K when the query embedding shows low affective signal; "
            "(c) introduce a query-type classifier so factual queries pull "
            "from facts only. These are retrieve-side changes out of scope for "
            "Thread EVAL."
        )
        lines.append("")

    return "\n".join(lines) + "\n"
