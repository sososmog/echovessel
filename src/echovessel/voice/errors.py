"""Voice provider error hierarchy.

These are the only exceptions that upper layers (runtime / channels /
proactive) catch around Voice calls. Mirrors `runtime/llm/errors.py`
deliberately — the retry/surface semantics are identical so upper layers
can use a shared catch pattern.

See docs/voice/01-spec-v0.1.md §2.3 and §11.

    VoiceError
      ├── VoiceTransientError     (retry: 5xx, timeout, rate limit)
      └── VoicePermanentError     (do not retry: 4xx, auth, invalid voice_id)
            └── VoiceBudgetError  (quota exhausted — surface to user;
                                   runtime disables voice until next start)
"""

from __future__ import annotations


class VoiceError(Exception):
    """Base for all Voice module failures."""


class VoiceTransientError(VoiceError):
    """Retry candidate: 5xx, timeout, rate limit, brief network fault.

    MVP runtime does NOT automatically retry Voice calls (unlike LLM calls).
    The user's natural recovery is "click play again" / "record again".
    """


class VoicePermanentError(VoiceError):
    """Non-retry: 4xx, auth fail, content policy, invalid voice_id."""


class VoiceBudgetError(VoicePermanentError):
    """Quota exhausted. Runtime surfaces to user and hard-stops voice
    operations until the daemon is restarted (spec §4.2 graceful degrade)."""


__all__ = [
    "VoiceError",
    "VoiceTransientError",
    "VoicePermanentError",
    "VoiceBudgetError",
]
