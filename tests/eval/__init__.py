"""Eval harness for MVP baseline metrics.

The harness replays `docs/memory/05-eval-corpus-v0.1.yaml` against the memory
pipeline and reports the four MVP core indicators:

    - Factual Recall F1 (target >= 0.80)
    - Emotional Peak Retention (target >= 0.95)
    - Over-recall FP Rate (target <= 0.15)
    - Deletion Compliance (target = 1.00)

Run the baseline with:

    python -m tests.eval.run_baseline

This is an offline-replay harness. It uses local stub callables for extraction,
reflection, embedding and judgement so a single run is deterministic and takes
seconds instead of minutes.
"""
