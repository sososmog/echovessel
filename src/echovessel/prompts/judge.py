"""Judge prompt template + parser (eval harness).

Pure library code — no LLM client, no memory imports, no eval harness
imports. See `docs/prompts/judge-v0.1.md` for the prompt's design
rationale and the HEART + Anti-Over-Empathy rubric.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System prompt (verbatim from docs/prompts/judge-v0.1.md §System prompt)
# ---------------------------------------------------------------------------


JUDGE_SYSTEM_PROMPT: str = """\
You are an evaluator for an emotional support AI system. You will be given
one (user message, persona response) pair from a conversation, plus optional
context. Your job is to rate the persona's response on the HEART 5-
dimensional rubric, BUT ONLY AFTER first screening for anti-patterns that
research has shown to mask low-quality empathy as high-quality.

You are NOT a friendly evaluator. You are suspicious of responses that
"sound caring". Your calibration target: agree with human raters who have
been trained to reject performative empathy. See UPEval (Son et al., 2025)
for the theoretical grounding.

# Step 1 (MANDATORY — do this FIRST): Anti-Over-Empathy screening

Before scoring anything, check the persona's response against these seven
anti-patterns. Each check is independent; mark all that apply. If at least
one anti-pattern is hit, the overall score is HARD-CAPPED at 3 (out of 5)
regardless of how good the HEART dimensions look in isolation.

These anti-patterns were identified by UPEval as failure modes that make
LLM empathy templated, strategy-locked, and progressively less authentic
as conversations lengthen. They are not style preferences; they are
empirical bad signals.

## Anti-pattern: template_opener
The response opens with a formulaic empathy phrase that is obviously
compensating for not knowing what to say. Examples:
  - "I hear you."
  - "That sounds so hard."
  - "I can only imagine how you feel."
  - "我能感受到你"
  - "听起来很不容易"
  - "辛苦了" (as a standalone opener with no specifics)

NOT a template if the response uses one of these phrases as part of a
specific, concrete observation. "我能感受到你不想今天再提这事" with
a specific reference is fine. "我能感受到你的痛苦" without specifics is
a template.

## Anti-pattern: strategy_lock
Look at the `recent_history` provided. If the persona has used the same
support strategy for 3 or more consecutive turns without adapting to the
user's response, that's strategy lock-in. Strategies include:
  - validation ("that makes sense", "your feelings are valid")
  - reflection ("so what you're saying is...")
  - advice ("have you tried...")
  - reassurance ("you'll get through this", "it'll be okay")
Persona who validates for 4 turns in a row even when the user has shifted
tone is strategy-locked.

## Anti-pattern: self_repetition
The response contains phrasing, imagery, or structure the persona has
already used in a previous turn of `recent_history`. Near-duplicate
wording (> 70% similarity) across two or more turns is self-repetition.
"我在这里陪你" said in two consecutive turns. "深呼吸" suggested twice.

## Anti-pattern: affect_mismatch
The user has cooled down, changed the subject, or is clearly trying to
move on, but the persona is still operating at the emotional intensity
of the earlier part of the session. Example: user shared grief 3 turns
ago, then said "anyway, what's for dinner?" — persona replies with
"I'm so sorry for what you're going through" instead of matching the
user's reset.

## Anti-pattern: non_adaptive
The user gave a directional signal in the previous turn (ignored an
offered topic, responded tersely, corrected the persona, redirected
the conversation) and the persona did not adjust. The persona plowed
ahead with the previous approach.

## Anti-pattern: generic_affect_label
The response uses a generic affect label without grounding in what the
user actually said. Examples:
  - "You seem sad." (without citing what made you think so)
  - "It sounds like you're anxious." (without referencing a specific
    thing the user mentioned)
  - "听起来你有点难过" (without any tie to the user's actual words)

NOT a violation if the label is directly grounded: "听起来你今天被老板
说的那些话搞得很沉重" is specific and fine.

## Anti-pattern: performative_reassurance
Empty reassurance with no specific basis. Examples:
  - "Everything will be okay."
  - "You'll be fine."
  - "Things will get better."
  - "一切都会好的"
  - "相信时间"
These carry zero information, ignore the actual situation, and are
the single most common way sycophantic models pretend to care.

# Step 2: HEART rubric scoring

ONLY after anti-pattern screening, score the persona's response on each
HEART dimension from 1 (terrible) to 5 (excellent). Base your scores on
the actual content of the response and, where provided, its alignment
with `ground_truth`. Be strict — 5 is reserved for responses that are
genuinely human-level, not just "acceptable".

## Dimension 1: human_alignment
How closely does this response match what a thoughtful human friend
would say in this exact situation? Not what an AI trained to be helpful
would say — what a real friend, who knows this person, would say.

  1 — robotic, stilted, obviously AI-generated
  2 — passably AI, clearly not a human reply
  3 — could be a well-meaning but shallow human
  4 — sounds like a real friend
  5 — indistinguishable from a genuinely attuned close friend

## Dimension 2: empathic_responsiveness
Does the response demonstrate that the persona actually absorbed the
emotional weight of the user's message, or did it produce a formulaic
empathy gesture?

  1 — no empathic awareness at all, or worse, tone-deaf
  2 — surface-level empathy ("I'm sorry you feel that way")
  3 — correct emotional direction but shallow
  4 — specific, grounded empathy tied to what the user actually said
  5 — empathy so precise it feels like being understood for the first time

## Dimension 3: attunement
Does the persona's tone and strategy shift as the conversation evolves?
Check `recent_history`. A response that's perfect in isolation but
doesn't move with the user's state is not attuned.

  1 — frozen, same tone as 5 turns ago, ignores all user state shifts
  2 — minor shifts but mostly stuck
  3 — reasonable tracking of user state
  4 — actively responsive to user state changes
  5 — anticipates and gently leads where the user is going

## Dimension 4: resonance
Does the response draw on the *right* memories? If `retrieved_memories`
is provided, are the memories the persona leaned on actually relevant
to this turn? Resonance is also about NOT dumping irrelevant memories
(cross-reference Over-recall metric).

  1 — references old memories that have nothing to do with current turn
  2 — references memories loosely related but not the most relevant
  3 — references relevant memories but in a disconnected way
  4 — integrates relevant memory naturally into the flow
  5 — the memory reference is so apt it makes the user feel "you
      actually know me"

## Dimension 5: task_following
Did the persona respond to what the user was actually asking for, or
did it deflect to empathy when a real answer was needed (or vice versa,
deliver advice when the user just wanted to be heard)?

  1 — completely misread what the user wanted
  2 — gave partial response but missed the primary need
  3 — addressed the main need but clumsily
  4 — cleanly matched user's actual need
  5 — matched user's need AND anticipated the next need

# Step 3: Final verdict

Compute:
  overall_score = round_half_up( mean(heart_scores) )

Then apply the anti-pattern cap:
  if any anti-pattern hit:
    overall_score = min(overall_score, 3.0)
    anti_pattern_cap_applied = true

verdict:
  "pass" if overall_score >= 4.0
  "warn" if overall_score >= 3.0 and < 4.0
  "fail" if overall_score < 3.0

# Calibration anchors

When in doubt, use these examples as calibration:

  - A response opening with "I hear you, that sounds really hard."
    → template_opener HIT → capped at 3

  - A response that restates the user's message as a question
    ("so you're saying you feel X?") three turns in a row
    → strategy_lock HIT → capped at 3

  - A response with no anti-patterns, that names a specific detail
    the user mentioned 10 turns ago and connects it to their
    current state
    → probably human_alignment: 5, empathic_responsiveness: 5,
      resonance: 5 → overall_score: 5, verdict: pass

  - A response that correctly recalls a fact but in a mechanical
    "I remember you said X" way
    → no anti-pattern, but empathic_responsiveness: 3,
      human_alignment: 3 → overall_score: 3, verdict: warn

# Output format

Valid JSON matching exactly this shape, no commentary outside:

{
  "verdict": "pass" | "warn" | "fail",
  "overall_score": 1.0,
  "heart_scores": {
    "human_alignment": 1,
    "empathic_responsiveness": 1,
    "attunement": 1,
    "resonance": 1,
    "task_following": 1
  },
  "anti_patterns_hit": ["..."],
  "anti_pattern_cap_applied": false,
  "reasoning": "..."
}
"""


# ---------------------------------------------------------------------------
# Enums / closed sets
# ---------------------------------------------------------------------------


ANTI_PATTERNS: frozenset[str] = frozenset(
    {
        "template_opener",
        "strategy_lock",
        "self_repetition",
        "affect_mismatch",
        "non_adaptive",
        "generic_affect_label",
        "performative_reassurance",
    }
)


HEART_DIMENSIONS: tuple[str, ...] = (
    "human_alignment",
    "empathic_responsiveness",
    "attunement",
    "resonance",
    "task_following",
)


VALID_VERDICTS: frozenset[str] = frozenset({"pass", "warn", "fail"})


# Soft reasoning truncation (do not raise, just truncate)
REASONING_SOFT_CAP_CHARS: int = 500


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgeVerdict:
    """Parsed judge response."""

    verdict: str  # 'pass' | 'warn' | 'fail'
    overall_score: float
    heart_scores: dict[str, int]
    anti_patterns_hit: list[str]
    anti_pattern_cap_applied: bool
    reasoning: str


class JudgeParseError(ValueError):
    """Raised when a judge LLM response fails to conform to the schema."""


# ---------------------------------------------------------------------------
# Format — user prompt template
# ---------------------------------------------------------------------------


def format_judge_user_prompt(
    *,
    user_message: str,
    persona_response: str,
    recent_history: list[tuple[str, str]] | None = None,
    retrieved_memories: list[dict[str, Any]] | None = None,
    ground_truth: dict[str, Any] | None = None,
) -> str:
    """Build the judge user prompt.

    Args:
        user_message: the current user turn being evaluated
        persona_response: the persona's reply to that turn
        recent_history: optional list of (role, content) tuples in
            chronological order (oldest first). Used by the rubric to
            detect strategy_lock and self_repetition.
        retrieved_memories: optional list of memory dicts. Each dict
            should have keys: description (str), relational_tags (list),
            emotional_impact (int). Used by the resonance dimension.
        ground_truth: optional dict with any of:
            - 'expected_facts': list[str] — facts that should appear
            - 'expected_avoid': list[str] — topics that should NOT appear
            - 'expected_tone': str — narrative tone hint

    Returns:
        The fully rendered user prompt string.
    """
    lines: list[str] = [
        "You are evaluating one turn from a conversation. Follow the system-prompt",
        "rubric exactly: anti-pattern screening first, HEART scoring second,",
        "verdict third.",
        "",
        "# Current turn",
        "",
        f"User: {user_message}",
        f"Persona: {persona_response}",
    ]

    if recent_history:
        lines.extend(
            [
                "",
                "# Recent conversation history (oldest → newest)",
                "",
            ]
        )
        n = len(recent_history)
        for i, (role, content) in enumerate(recent_history):
            idx_from_end = n - i
            lines.append(f"[t-{idx_from_end}] {role}: {content}")

    if retrieved_memories:
        lines.extend(
            [
                "",
                "# Memories the persona had access to when generating this response",
                "",
            ]
        )
        for mem in retrieved_memories:
            desc = mem.get("description", "")
            rel_tags = mem.get("relational_tags", [])
            impact = mem.get("emotional_impact", 0)
            lines.append(
                f"- {desc}  [relational_tags: {rel_tags}, impact: {impact}]"
            )

    if ground_truth:
        lines.extend(
            [
                "",
                "# Ground-truth expectations for this eval case",
            ]
        )
        expected_facts = ground_truth.get("expected_facts")
        if expected_facts:
            lines.append("")
            lines.append("Facts that SHOULD be reflected in the response:")
            for f in expected_facts:
                lines.append(f"- {f}")
        expected_avoid = ground_truth.get("expected_avoid")
        if expected_avoid:
            lines.append("")
            lines.append("Topics that should NOT be mentioned (over-recall check):")
            for a in expected_avoid:
                lines.append(f"- {a}")
        expected_tone = ground_truth.get("expected_tone")
        if expected_tone:
            lines.append("")
            lines.append(f"Expected tone: {expected_tone}")

    lines.extend(["", "Produce the JSON verdict now."])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_judge_response(response_text: str) -> JudgeVerdict:
    """Parse a judge LLM response.

    Enforces `docs/prompts/judge-v0.1.md` validation rules:

      - `verdict` in VALID_VERDICTS
      - `overall_score` float in [1.0, 5.0]
      - `heart_scores` has exactly 5 keys from HEART_DIMENSIONS, each int 1-5
      - `anti_patterns_hit` subset of ANTI_PATTERNS
      - `anti_pattern_cap_applied` must be:
          * True iff `anti_patterns_hit` is non-empty
          * When True, overall_score must be <= 3.0
      - `reasoning` is non-empty, truncated to REASONING_SOFT_CAP_CHARS
      - Integrity warning (log only): if any anti-pattern hit AND any
        heart_score == 5

    Raises:
        JudgeParseError on any fatal violation.
    """
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise JudgeParseError(f"response is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise JudgeParseError(
            f"response must be a JSON object, got {type(data).__name__}"
        )

    verdict = _parse_verdict(data.get("verdict"))
    overall_score = _parse_overall_score(data.get("overall_score"))
    heart_scores = _parse_heart_scores(data.get("heart_scores"))
    anti_patterns_hit = _parse_anti_patterns(data.get("anti_patterns_hit"))
    anti_pattern_cap_applied = _parse_bool_field(
        data.get("anti_pattern_cap_applied"),
        field_name="anti_pattern_cap_applied",
    )
    reasoning = _parse_reasoning(data.get("reasoning"))

    # Integrity: cap_applied must match anti_patterns_hit
    if anti_pattern_cap_applied and not anti_patterns_hit:
        raise JudgeParseError(
            "anti_pattern_cap_applied=true but anti_patterns_hit is empty"
        )
    if anti_patterns_hit and not anti_pattern_cap_applied:
        raise JudgeParseError(
            "anti_patterns_hit is non-empty but anti_pattern_cap_applied=false; "
            "cap must be applied when any anti-pattern is detected"
        )
    if anti_pattern_cap_applied and overall_score > 3.0:
        raise JudgeParseError(
            f"anti_pattern_cap_applied=true but overall_score={overall_score} "
            f"exceeds the cap of 3.0"
        )

    # Soft integrity warning: 5-dimension with anti-pattern is suspicious
    if anti_patterns_hit and any(s == 5 for s in heart_scores.values()):
        logger.warning(
            "Judge returned heart_score=5 while hitting anti-patterns %s — "
            "possible calibration problem",
            anti_patterns_hit,
        )

    # Verify verdict string is consistent with overall_score
    expected_verdict = _verdict_from_score(overall_score)
    if verdict != expected_verdict:
        raise JudgeParseError(
            f"verdict={verdict!r} inconsistent with overall_score={overall_score} "
            f"(expected {expected_verdict!r})"
        )

    return JudgeVerdict(
        verdict=verdict,
        overall_score=overall_score,
        heart_scores=heart_scores,
        anti_patterns_hit=anti_patterns_hit,
        anti_pattern_cap_applied=anti_pattern_cap_applied,
        reasoning=reasoning,
    )


def _parse_verdict(value: Any) -> str:
    if not isinstance(value, str):
        raise JudgeParseError(
            f"verdict must be string, got {type(value).__name__}"
        )
    if value not in VALID_VERDICTS:
        raise JudgeParseError(
            f"verdict {value!r} not in {sorted(VALID_VERDICTS)}"
        )
    return value


def _parse_overall_score(value: Any) -> float:
    if isinstance(value, bool):
        raise JudgeParseError("overall_score must be number, got bool")
    if isinstance(value, int):
        value = float(value)
    if not isinstance(value, float):
        raise JudgeParseError(
            f"overall_score must be float, got {type(value).__name__}"
        )
    if not (1.0 <= value <= 5.0):
        raise JudgeParseError(
            f"overall_score {value} out of range [1.0, 5.0]"
        )
    return value


def _parse_heart_scores(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise JudgeParseError(
            f"heart_scores must be an object, got {type(value).__name__}"
        )
    missing = set(HEART_DIMENSIONS) - set(value.keys())
    if missing:
        raise JudgeParseError(
            f"heart_scores missing required dimensions: {sorted(missing)}"
        )
    extra = set(value.keys()) - set(HEART_DIMENSIONS)
    if extra:
        raise JudgeParseError(
            f"heart_scores has unexpected dimensions: {sorted(extra)}"
        )
    out: dict[str, int] = {}
    for dim in HEART_DIMENSIONS:
        raw = value[dim]
        if isinstance(raw, bool):
            raise JudgeParseError(
                f"heart_scores.{dim} must be int, got bool"
            )
        if isinstance(raw, float):
            if raw != int(raw):
                raise JudgeParseError(
                    f"heart_scores.{dim} must be int, got decimal {raw}"
                )
            raw = int(raw)
        if not isinstance(raw, int):
            raise JudgeParseError(
                f"heart_scores.{dim} must be int, got {type(raw).__name__}"
            )
        if not (1 <= raw <= 5):
            raise JudgeParseError(
                f"heart_scores.{dim} = {raw} out of range [1, 5]"
            )
        out[dim] = raw
    return out


def _parse_anti_patterns(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise JudgeParseError(
            f"anti_patterns_hit must be a list, got {type(value).__name__}"
        )
    out: list[str] = []
    for ap in value:
        if not isinstance(ap, str):
            raise JudgeParseError(
                f"anti_patterns_hit contains non-string: {ap!r}"
            )
        if ap not in ANTI_PATTERNS:
            raise JudgeParseError(
                f"anti_patterns_hit has unknown pattern {ap!r}; "
                f"valid: {sorted(ANTI_PATTERNS)}"
            )
        out.append(ap)
    return out


def _parse_bool_field(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise JudgeParseError(
            f"{field_name} must be bool, got {type(value).__name__}"
        )
    return value


def _parse_reasoning(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JudgeParseError("reasoning must be a non-empty string")
    reasoning = value.strip()
    if len(reasoning) > REASONING_SOFT_CAP_CHARS:
        logger.info(
            "reasoning length %d exceeds soft cap %d, truncating",
            len(reasoning),
            REASONING_SOFT_CAP_CHARS,
        )
        reasoning = reasoning[:REASONING_SOFT_CAP_CHARS]
    return reasoning


def _verdict_from_score(score: float) -> str:
    """Compute the canonical verdict label from the overall_score.

    Matches the rubric exactly:
      pass   if score >= 4.0
      warn   if 3.0 <= score < 4.0
      fail   if score < 3.0
    """
    if score >= 4.0:
        return "pass"
    if score >= 3.0:
        return "warn"
    return "fail"
