"""LLMProvider Protocol and tier enum.

See docs/runtime/01-spec-v0.1.md §6.1 and §6.2.2.

Runtime holds ONE provider instance. Every call site declares its semantic
tier (SMALL/MEDIUM/LARGE) at the call point; the provider internally maps
tier → concrete model name.

Tier assignment for EchoVessel (§6.6):

    SMALL  — extraction / reflection (consolidate background, cheap/fast)
    MEDIUM — judge (eval harness, strict but not the most expensive)
    LARGE  — interaction / proactive reply (user is waiting, premium quality)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Protocol, runtime_checkable


class LLMTier(StrEnum):
    """Semantic quality/cost tier for an LLM call site.

    Each call site declares the tier it wants; the provider maps tier → model.
    Users configure ONE provider plus optional per-tier overrides; they never
    need to know which specific model each call site ends up using.
    """

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@runtime_checkable
class LLMProvider(Protocol):
    """Async LLM provider contract.

    All methods are async. `extract_fn` / `reflect_fn` / `turn_handler` all
    share a single asyncio event loop, so any sync provider would block it.
    """

    @property
    def provider_name(self) -> str:
        """One of 'anthropic' / 'openai_compat' / 'stub'."""
        ...

    def model_for(self, tier: LLMTier) -> str:
        """Resolve which concrete model the provider uses for the given tier.

        Exposed for logging / audit / local-first disclosure; not used in the
        hot path (the tier is passed directly to complete/stream).
        """
        ...

    async def complete(
        self,
        system: str,
        user: str,
        *,
        tier: LLMTier = LLMTier.MEDIUM,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> str:
        """Single-shot text completion. Returns the raw text body.

        On transient HTTP failure (5xx, timeout, rate limit): raise
        LLMTransientError. On permanent failure (4xx, auth, content filter):
        raise LLMPermanentError.
        """
        ...

    async def stream(
        self,
        system: str,
        user: str,
        *,
        tier: LLMTier = LLMTier.MEDIUM,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """Token-by-token streaming. Yields text deltas.

        Stub implementations MAY fall back to `await complete()` followed by
        one yield.
        """
        ...


__all__ = ["LLMTier", "LLMProvider"]
