"""Tests for echovessel.prompts.judge."""

from __future__ import annotations

import json
import logging

import pytest

from echovessel.prompts.judge import (
    ANTI_PATTERNS,
    HEART_DIMENSIONS,
    JUDGE_SYSTEM_PROMPT,
    JudgeParseError,
    JudgeVerdict,
    format_judge_user_prompt,
    parse_judge_response,
)

# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_heart_dimensions_are_fixed_five():
    assert HEART_DIMENSIONS == (
        "human_alignment",
        "empathic_responsiveness",
        "attunement",
        "resonance",
        "task_following",
    )


def test_anti_patterns_are_exactly_seven():
    assert frozenset(
        {
            "template_opener",
            "strategy_lock",
            "self_repetition",
            "affect_mismatch",
            "non_adaptive",
            "generic_affect_label",
            "performative_reassurance",
        }
    ) == ANTI_PATTERNS


def test_system_prompt_starts_with_evaluator_line():
    assert JUDGE_SYSTEM_PROMPT.startswith(
        "You are an evaluator for an emotional support AI system"
    )


def test_system_prompt_references_upeval():
    # The UPEval citation is load-bearing — if this fails someone has
    # diluted the anti-over-empathy framing
    assert "UPEval" in JUDGE_SYSTEM_PROMPT
    assert "HARD-CAPPED at 3" in JUDGE_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


def test_format_judge_minimal_prompt():
    out = format_judge_user_prompt(
        user_message="anyway, what's for dinner?",
        persona_response="要不要试你周一想去的那家居酒屋？",
    )
    assert "User: anyway, what's for dinner?" in out
    assert "Persona: 要不要试你周一想去的那家居酒屋？" in out
    assert "Produce the JSON verdict now." in out


def test_format_judge_with_history():
    out = format_judge_user_prompt(
        user_message="ok",
        persona_response="hmm",
        recent_history=[
            ("user", "turn 1 user"),
            ("persona", "turn 1 persona"),
            ("user", "turn 2 user"),
        ],
    )
    # History indices count from end: t-3, t-2, t-1
    assert "[t-3] user: turn 1 user" in out
    assert "[t-2] persona: turn 1 persona" in out
    assert "[t-1] user: turn 2 user" in out


def test_format_judge_with_retrieved_memories():
    out = format_judge_user_prompt(
        user_message="q",
        persona_response="r",
        retrieved_memories=[
            {
                "description": "用户很爱猫 Mochi",
                "relational_tags": ["identity-bearing"],
                "emotional_impact": 4,
            }
        ],
    )
    assert "用户很爱猫 Mochi" in out
    assert "identity-bearing" in out
    assert "impact: 4" in out


def test_format_judge_with_ground_truth():
    out = format_judge_user_prompt(
        user_message="q",
        persona_response="r",
        ground_truth={
            "expected_facts": ["user has a cat named Mochi"],
            "expected_avoid": ["father's death"],
            "expected_tone": "light, reset",
        },
    )
    assert "Facts that SHOULD be reflected" in out
    assert "user has a cat named Mochi" in out
    assert "should NOT be mentioned" in out
    assert "father's death" in out
    assert "Expected tone: light, reset" in out


# ---------------------------------------------------------------------------
# Parser — valid
# ---------------------------------------------------------------------------


def _valid_payload(
    *,
    verdict: str = "pass",
    overall: float = 4.4,
    heart: dict | None = None,
    anti: list[str] | None = None,
    cap: bool = False,
    reasoning: str = "specific, grounded, no templates",
) -> str:
    default_heart = {
        "human_alignment": 4,
        "empathic_responsiveness": 5,
        "attunement": 4,
        "resonance": 4,
        "task_following": 5,
    }
    return json.dumps(
        {
            "verdict": verdict,
            "overall_score": overall,
            "heart_scores": heart or default_heart,
            "anti_patterns_hit": anti or [],
            "anti_pattern_cap_applied": cap,
            "reasoning": reasoning,
        }
    )


def test_parse_valid_pass_verdict():
    result = parse_judge_response(_valid_payload())
    assert isinstance(result, JudgeVerdict)
    assert result.verdict == "pass"
    assert result.overall_score == pytest.approx(4.4)
    assert result.heart_scores["empathic_responsiveness"] == 5
    assert result.anti_patterns_hit == []
    assert result.anti_pattern_cap_applied is False


def test_parse_valid_fail_with_anti_patterns():
    result = parse_judge_response(
        _valid_payload(
            verdict="fail",
            overall=2.0,
            heart={
                "human_alignment": 2,
                "empathic_responsiveness": 2,
                "attunement": 1,
                "resonance": 1,
                "task_following": 2,
            },
            anti=["template_opener", "performative_reassurance"],
            cap=True,
            reasoning="opens with template + empty reassurance",
        )
    )
    assert result.verdict == "fail"
    assert "template_opener" in result.anti_patterns_hit
    assert result.anti_pattern_cap_applied is True


def test_parse_valid_warn_at_boundary():
    result = parse_judge_response(
        _valid_payload(
            verdict="warn",
            overall=3.0,
            heart=dict.fromkeys(HEART_DIMENSIONS, 3),
        )
    )
    assert result.verdict == "warn"


def test_parse_int_overall_score_coerced_to_float():
    """Some LLM outputs emit 5 instead of 5.0; accept and coerce."""
    result = parse_judge_response(
        _valid_payload(
            verdict="pass",
            overall=5,
            heart=dict.fromkeys(HEART_DIMENSIONS, 5),
        )
    )
    assert isinstance(result.overall_score, float)
    assert result.overall_score == 5.0


# ---------------------------------------------------------------------------
# Parser — failure modes
# ---------------------------------------------------------------------------


def test_parse_invalid_json_raises():
    with pytest.raises(JudgeParseError, match="not valid JSON"):
        parse_judge_response("not json")


def test_parse_bad_verdict_raises():
    with pytest.raises(JudgeParseError, match=r"verdict 'excellent' not in"):
        parse_judge_response(_valid_payload(verdict="excellent"))


def test_parse_overall_score_out_of_range_raises():
    with pytest.raises(JudgeParseError, match=r"overall_score 6\.0 out of range"):
        parse_judge_response(
            _valid_payload(
                verdict="pass",
                overall=6.0,
                heart=dict.fromkeys(HEART_DIMENSIONS, 5),
            )
        )


def test_parse_heart_scores_missing_dimension_raises():
    with pytest.raises(JudgeParseError, match="missing required dimensions"):
        parse_judge_response(
            _valid_payload(
                heart={
                    "human_alignment": 4,
                    "empathic_responsiveness": 4,
                    "attunement": 4,
                    "resonance": 4,
                    # task_following missing
                }
            )
        )


def test_parse_heart_scores_extra_dimension_raises():
    with pytest.raises(JudgeParseError, match="unexpected dimensions"):
        parse_judge_response(
            _valid_payload(
                heart={
                    "human_alignment": 4,
                    "empathic_responsiveness": 4,
                    "attunement": 4,
                    "resonance": 4,
                    "task_following": 4,
                    "empathy_score": 5,  # bogus extra
                }
            )
        )


def test_parse_heart_score_out_of_range_raises():
    with pytest.raises(JudgeParseError, match="out of range"):
        parse_judge_response(
            _valid_payload(
                heart={
                    "human_alignment": 6,  # > 5
                    "empathic_responsiveness": 4,
                    "attunement": 4,
                    "resonance": 4,
                    "task_following": 4,
                }
            )
        )


def test_parse_heart_score_decimal_raises():
    with pytest.raises(JudgeParseError, match="must be int, got decimal"):
        parse_judge_response(
            _valid_payload(
                heart={
                    "human_alignment": 4.5,
                    "empathic_responsiveness": 4,
                    "attunement": 4,
                    "resonance": 4,
                    "task_following": 4,
                }
            )
        )


def test_parse_unknown_anti_pattern_raises():
    with pytest.raises(JudgeParseError, match="unknown pattern"):
        parse_judge_response(
            _valid_payload(
                verdict="warn",
                overall=3.0,
                heart=dict.fromkeys(HEART_DIMENSIONS, 3),
                anti=["template_opener", "made_up_pattern"],
                cap=True,
            )
        )


def test_parse_cap_applied_without_anti_patterns_raises():
    with pytest.raises(
        JudgeParseError, match="anti_patterns_hit is empty"
    ):
        parse_judge_response(
            _valid_payload(
                verdict="warn",
                overall=3.0,
                heart=dict.fromkeys(HEART_DIMENSIONS, 3),
                anti=[],
                cap=True,
            )
        )


def test_parse_anti_patterns_without_cap_raises():
    """If anti-patterns hit, cap must be applied. Inconsistency = bug."""
    with pytest.raises(JudgeParseError, match="cap must be applied"):
        parse_judge_response(
            _valid_payload(
                verdict="warn",
                overall=3.0,
                heart=dict.fromkeys(HEART_DIMENSIONS, 3),
                anti=["template_opener"],
                cap=False,
            )
        )


def test_parse_cap_applied_but_score_exceeds_cap_raises():
    with pytest.raises(
        JudgeParseError, match=r"overall_score=4\.0 exceeds the cap of 3\.0"
    ):
        parse_judge_response(
            _valid_payload(
                verdict="pass",
                overall=4.0,
                heart=dict.fromkeys(HEART_DIMENSIONS, 4),
                anti=["template_opener"],
                cap=True,
            )
        )


def test_parse_verdict_inconsistent_with_score_raises():
    """verdict='pass' with overall_score=2.0 is a contradiction."""
    with pytest.raises(JudgeParseError, match="inconsistent with overall_score"):
        parse_judge_response(
            _valid_payload(
                verdict="pass",
                overall=2.0,
                heart=dict.fromkeys(HEART_DIMENSIONS, 2),
                anti=[],
                cap=False,
            )
        )


def test_parse_empty_reasoning_raises():
    with pytest.raises(JudgeParseError, match="reasoning must be a non-empty"):
        parse_judge_response(_valid_payload(reasoning="   "))


def test_parse_long_reasoning_truncated():
    long_reason = "x" * 1200
    result = parse_judge_response(_valid_payload(reasoning=long_reason))
    assert len(result.reasoning) <= 500


def test_parse_anti_pattern_with_heart_five_warns(caplog):
    """If any heart_score is 5 while an anti-pattern is hit, log a warning.

    This is a soft integrity check — the cap will still apply, but the
    calibration looks suspicious so we want visibility.
    """
    caplog.set_level(logging.WARNING, logger="echovessel.prompts.judge")
    parse_judge_response(
        _valid_payload(
            verdict="warn",
            overall=3.0,
            heart={
                "human_alignment": 5,  # 5 while cap is active
                "empathic_responsiveness": 3,
                "attunement": 3,
                "resonance": 3,
                "task_following": 3,
            },
            anti=["template_opener"],
            cap=True,
        )
    )
    assert any(
        "possible calibration problem" in r.getMessage()
        for r in caplog.records
    )
