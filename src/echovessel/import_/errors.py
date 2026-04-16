"""Exception hierarchy for the universal importer pipeline.

Separated into transient / permanent failure classes so the orchestrator
in `pipeline.py` can distinguish between "pause and wait for resume" and
"fail the entire pipeline immediately".

Spec references:
- `docs/import/03-code-tracker.md` §2.6 (failure mode classification)
- `docs/import/01-import-spec-v0.1.md` §8.3 (ImportError taxonomy)
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base class for every importer pipeline error."""


class NormalizationError(PipelineError):
    """Raised when a file cannot be decoded into UTF-8 text.

    Treated as a *permanent* failure — pipeline aborts immediately and
    emits `pipeline.done` with ``status="failed"``.
    """


class ChunkingError(PipelineError):
    """Raised when chunking logic hits an invariant violation.

    Treated as permanent; chunking is deterministic and any failure
    indicates a programming bug, not a transient condition.
    """


class ExtractionError(PipelineError):
    """Raised when the LLM output cannot be parsed into the expected
    JSON schema.

    May be *transient* (LLM output was truncated, retry might succeed)
    or *permanent* (schema violation after validation). The caller sets
    the ``fatal`` attribute to steer the dispatcher.
    """

    def __init__(self, message: str, *, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


class RoutingError(PipelineError):
    """Raised when a validated `ContentItem` cannot be dispatched to
    the memory import API (e.g. unknown content_type, missing payload
    keys).

    Always *permanent*.
    """


class EmbedError(PipelineError):
    """Raised when the embed pass cannot write vectors.

    Raised eagerly when ``embed_fn`` is ``None`` **and** the pipeline
    produced memory writes that need embeddings — this is the hard
    constraint from Thread M-round3 §7.4 (vector_search depends on it).
    """


__all__ = [
    "PipelineError",
    "NormalizationError",
    "ChunkingError",
    "ExtractionError",
    "RoutingError",
    "EmbedError",
]
