"""Baseline eval runner — the one-command entry point.

    python -m tests.eval.run_baseline

Loads `docs/memory/05-eval-corpus-v0.1.yaml`, replays the 14 days through the
real memory pipeline, computes the four MVP metrics, prints the summary and
writes the long-form markdown report to
`docs/memory/eval-runs/YYYY-MM-DD-baseline-<commit>.md`.

This script is NOT a pytest test. `pytest tests/eval/` runs
`test_metrics.py / test_corpus_loader.py / test_scenario.py`; this file is
a CLI-only module and pytest skips it because its name doesn't match
`test_*.py`.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path

from tests.eval.corpus_loader import CORPUS_PATH, load_corpus
from tests.eval.metrics import compute_all
from tests.eval.report import ReportMeta, render_console, render_markdown
from tests.eval.scenario import run_scenario

REPORT_DIR = Path("docs/memory/eval-runs")


def _git_commit() -> str:
    """Best-effort short commit hash. Falls back to 'nogit' if unavailable."""
    env = dict(os.environ)
    env.pop("GIT_DIR", None)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        return out.stdout.strip() or "nogit"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "nogit"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m tests.eval.run_baseline",
        description="Run the MVP baseline eval and emit a markdown report.",
    )
    p.add_argument(
        "--corpus",
        type=Path,
        default=CORPUS_PATH,
        help="Path to the eval corpus YAML (default: %(default)s)",
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="Skip writing the markdown report file (still prints the summary)",
    )
    p.add_argument(
        "--fixed-time",
        type=str,
        default=None,
        help=(
            "ISO 8601 timestamp to pin the report metadata 'run_at' field — "
            "useful for reproducibility checks. Default: current time."
        ),
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    print(f"[info] loading corpus: {args.corpus}")
    corpus = load_corpus(args.corpus)
    total_sessions = sum(len(d.sessions) for d in corpus.days)
    print(
        f"[info] {corpus.total_days} days · {total_sessions} sessions · "
        f"{len(corpus.golden_questions)} golden questions"
    )
    print("[info] LLM provider: local stub callables (offline replay mode)")

    print("[info] running scenario...")
    scenario_result = run_scenario(corpus)
    print(
        f"[info] extracted {len(scenario_result.extractions)} sessions · "
        f"captured {len(scenario_result.golden_results)} golden retrievals · "
        f"deletions applied {len(scenario_result.deletions_applied)}/"
        f"{len(corpus.ground_truth.deletion_targets)}"
    )

    metrics = compute_all(corpus, scenario_result)

    run_at = (
        datetime.fromisoformat(args.fixed_time)
        if args.fixed_time
        else datetime.now()
    )
    meta = ReportMeta(
        corpus_name=corpus.name,
        corpus_version=corpus.version,
        commit_hash=_git_commit(),
        run_at=run_at,
    )

    print()
    print(render_console(metrics, meta))

    if args.no_report:
        print()
        print("[info] --no-report set, skipping report file emission")
        return 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = (
        REPORT_DIR
        / f"{run_at.date().isoformat()}-baseline-{meta.commit_hash}.md"
    )
    report_path.write_text(
        render_markdown(metrics, corpus, meta), encoding="utf-8"
    )
    print()
    print(f"Report saved to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
