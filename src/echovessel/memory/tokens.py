"""Token count estimator using tiktoken's cl100k_base encoding.

Used for session max_length safety thresholds — NOT for precise billing.
For Claude specifically, cl100k_base slightly overestimates token counts
(especially on Chinese), which is fine for a threshold check because the
system will close sessions slightly earlier rather than overrun context.

See docs/memory/04-schema-v0.2.md Q-schema-3.
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _encoder() -> tiktoken.Encoding:
    """Lazy-load the encoder. Network-free, cached after first call."""
    return tiktoken.get_encoding("cl100k_base")


def estimate_tokens(text: str) -> int:
    """Approximate token count for `text`.

    Uses OpenAI's cl100k_base BPE encoding. For English this is ~exact,
    for Chinese it's biased 5-15% high (conservative). Safe for session
    max_length decisions, not suitable for API cost accounting.
    """
    if not text:
        return 0
    return len(_encoder().encode(text))
