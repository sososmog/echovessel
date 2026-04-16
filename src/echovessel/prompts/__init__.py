"""LLM prompt templates and parsers.

Pure templates — no LLM client, no memory/runtime imports. Runtime is the
layer that wires these into `extract_fn` / `reflect_fn` / `judge_fn`
callables by combining the templates with an LLM provider.

Layering rule (enforced by import-linter):

    prompts → core only

prompts MUST NOT import from memory, voice, channels, or runtime. See
`PROJECT_TRACKER.md` §3.1.
"""

from echovessel.prompts.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    MAX_EMOTION_TAGS,
    RELATIONAL_TAG_VOCABULARY,
    ExtractionParseError,
    ExtractionParseResult,
    RawExtractedEvent,
    format_extraction_user_prompt,
    parse_extraction_response,
)
from echovessel.prompts.judge import (
    ANTI_PATTERNS,
    HEART_DIMENSIONS,
    JUDGE_SYSTEM_PROMPT,
    REASONING_SOFT_CAP_CHARS,
    VALID_VERDICTS,
    JudgeParseError,
    JudgeVerdict,
    format_judge_user_prompt,
    parse_judge_response,
)
from echovessel.prompts.reflection import (
    MAX_THOUGHTS,
    RECOMMENDED_IMPACT_BOUND,
    REFLECTION_SYSTEM_PROMPT,
    RawExtractedThought,
    ReflectionParseError,
    ReflectionParseResult,
    format_reflection_user_prompt,
    parse_reflection_response,
)

__all__ = [
    # extraction
    "EXTRACTION_SYSTEM_PROMPT",
    "MAX_EMOTION_TAGS",
    "RELATIONAL_TAG_VOCABULARY",
    "ExtractionParseError",
    "ExtractionParseResult",
    "RawExtractedEvent",
    "format_extraction_user_prompt",
    "parse_extraction_response",
    # reflection
    "MAX_THOUGHTS",
    "RECOMMENDED_IMPACT_BOUND",
    "REFLECTION_SYSTEM_PROMPT",
    "RawExtractedThought",
    "ReflectionParseError",
    "ReflectionParseResult",
    "format_reflection_user_prompt",
    "parse_reflection_response",
    # judge
    "ANTI_PATTERNS",
    "HEART_DIMENSIONS",
    "JUDGE_SYSTEM_PROMPT",
    "REASONING_SOFT_CAP_CHARS",
    "VALID_VERDICTS",
    "JudgeParseError",
    "JudgeVerdict",
    "format_judge_user_prompt",
    "parse_judge_response",
]
