"""LLM provider error hierarchy.

These are the only exceptions that runtime code catches around LLM calls
(see spec §6.3 and §8.3 for the retry/surface decisions).

    LLMError
      ├── LLMTransientError    (retry: 5xx, timeout, rate limit)
      └── LLMPermanentError    (do not retry: 4xx, auth, content filter)
            └── LLMBudgetError (quota exhausted — surface to user)
"""

from __future__ import annotations


class LLMError(Exception):
    """Base for all LLM provider failures."""


class LLMTransientError(LLMError):
    """Retry candidate: 5xx, timeout, rate limit."""


class LLMPermanentError(LLMError):
    """Non-retry: 4xx, auth fail, content filter."""


class LLMBudgetError(LLMPermanentError):
    """Quota exhausted. Surface to user, don't retry."""


__all__ = [
    "LLMError",
    "LLMTransientError",
    "LLMPermanentError",
    "LLMBudgetError",
]
