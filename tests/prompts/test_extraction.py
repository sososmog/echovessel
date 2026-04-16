"""Tests for echovessel.prompts.extraction."""

from __future__ import annotations

import json
import logging

import pytest

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

# ---------------------------------------------------------------------------
# Constants / metadata
# ---------------------------------------------------------------------------


def test_system_prompt_starts_with_extraction_engine_line():
    # Stability guard — the first line of the prompt is the identity line
    # Thread P tuned carefully. If this fails you probably tampered with
    # the system prompt string (do NOT).
    assert EXTRACTION_SYSTEM_PROMPT.startswith(
        "You are an extraction engine for a long-term digital companion"
    )


def test_relational_tag_vocabulary_is_exactly_six_values():
    assert frozenset(
        {
            "identity-bearing",
            "unresolved",
            "vulnerability",
            "turning-point",
            "correction",
            "commitment",
        }
    ) == RELATIONAL_TAG_VOCABULARY


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


def test_format_extraction_user_prompt_basic():
    out = format_extraction_user_prompt(
        session_id="s_test",
        started_at_iso="2026-04-14T23:00:00",
        closed_at_iso="2026-04-15T00:00:00",
        message_count=3,
        messages=[
            ("23:00", "user", "hi"),
            ("23:01", "persona", "hey"),
            ("23:02", "user", "how are you"),
        ],
    )
    assert "session_id: s_test" in out
    assert "[23:00] user: hi" in out
    assert "[23:02] user: how are you" in out
    assert "Produce the JSON output now." in out


def test_format_extraction_user_prompt_empty_messages():
    out = format_extraction_user_prompt(
        session_id="s_empty",
        started_at_iso="2026-04-15T00:00:00",
        closed_at_iso="2026-04-15T00:00:05",
        message_count=0,
        messages=[],
    )
    # Should still render without error
    assert "Messages (chronological):" in out
    assert "Produce the JSON output now." in out


# ---------------------------------------------------------------------------
# Parser — valid inputs
# ---------------------------------------------------------------------------


def _wrap(events: list[dict], notes: str = "ok") -> str:
    return json.dumps({"events": events, "self_check_notes": notes})


def test_parse_valid_minimal_event():
    result = parse_extraction_response(
        _wrap(
            [
                {
                    "description": "user shared a small joke about work",
                    "emotional_impact": 2,
                    "emotion_tags": ["joy"],
                    "relational_tags": [],
                }
            ]
        )
    )
    assert isinstance(result, ExtractionParseResult)
    assert len(result.events) == 1
    ev = result.events[0]
    assert isinstance(ev, RawExtractedEvent)
    assert ev.description == "user shared a small joke about work"
    assert ev.emotional_impact == 2
    assert ev.emotion_tags == ["joy"]
    assert ev.relational_tags == []
    assert result.self_check_notes == "ok"


def test_parse_empty_events_list_is_allowed():
    result = parse_extraction_response(_wrap([], notes="no user disclosure"))
    assert result.events == []
    assert result.self_check_notes == "no user disclosure"


def test_parse_multiple_events():
    result = parse_extraction_response(
        _wrap(
            [
                {
                    "description": "first event",
                    "emotional_impact": -3,
                    "emotion_tags": [],
                    "relational_tags": [],
                },
                {
                    "description": "second event",
                    "emotional_impact": 5,
                    "emotion_tags": ["joy"],
                    "relational_tags": ["identity-bearing"],
                },
            ]
        )
    )
    assert len(result.events) == 2
    assert result.events[0].emotional_impact == -3
    assert result.events[1].relational_tags == ["identity-bearing"]


def test_parse_emotion_tags_lowercased():
    """Tags should be lowercased silently — LLMs often forget case."""
    result = parse_extraction_response(
        _wrap(
            [
                {
                    "description": "something happened",
                    "emotional_impact": 1,
                    "emotion_tags": ["JOY", "Relief"],
                    "relational_tags": [],
                }
            ]
        )
    )
    assert result.events[0].emotion_tags == ["joy", "relief"]


def test_parse_int_valued_float_impact_accepted():
    """LLM outputs like 5.0 should coerce to 5 cleanly."""
    result = parse_extraction_response(
        _wrap(
            [
                {
                    "description": "x",
                    "emotional_impact": 5.0,
                    "emotion_tags": [],
                    "relational_tags": [],
                }
            ]
        )
    )
    assert result.events[0].emotional_impact == 5


# ---------------------------------------------------------------------------
# Parser — failure modes
# ---------------------------------------------------------------------------


def test_parse_invalid_json_raises():
    with pytest.raises(ExtractionParseError, match="not valid JSON"):
        parse_extraction_response("not a json at all")


def test_parse_top_level_array_raises():
    with pytest.raises(ExtractionParseError, match="must be a JSON object"):
        parse_extraction_response(json.dumps([]))


def test_parse_missing_events_key_raises():
    with pytest.raises(ExtractionParseError, match="missing required key 'events'"):
        parse_extraction_response(json.dumps({"self_check_notes": "ok"}))


def test_parse_events_not_a_list_raises():
    with pytest.raises(ExtractionParseError, match="'events' must be a list"):
        parse_extraction_response(json.dumps({"events": "nope"}))


def test_parse_empty_description_raises():
    with pytest.raises(ExtractionParseError, match="description must be a non-empty"):
        parse_extraction_response(
            _wrap(
                [
                    {
                        "description": "   ",
                        "emotional_impact": 0,
                        "emotion_tags": [],
                        "relational_tags": [],
                    }
                ]
            )
        )


def test_parse_impact_out_of_range_raises():
    with pytest.raises(ExtractionParseError, match=r"-15 out of range"):
        parse_extraction_response(
            _wrap(
                [
                    {
                        "description": "x",
                        "emotional_impact": -15,
                        "emotion_tags": [],
                        "relational_tags": [],
                    }
                ]
            )
        )


def test_parse_impact_positive_out_of_range_raises():
    with pytest.raises(ExtractionParseError, match=r"11 out of range"):
        parse_extraction_response(
            _wrap(
                [
                    {
                        "description": "x",
                        "emotional_impact": 11,
                        "emotion_tags": [],
                        "relational_tags": [],
                    }
                ]
            )
        )


def test_parse_impact_decimal_raises():
    with pytest.raises(ExtractionParseError, match="must be an integer"):
        parse_extraction_response(
            _wrap(
                [
                    {
                        "description": "x",
                        "emotional_impact": 3.5,
                        "emotion_tags": [],
                        "relational_tags": [],
                    }
                ]
            )
        )


def test_parse_impact_bool_rejected():
    """bool is a subclass of int in Python — must be explicitly rejected."""
    with pytest.raises(ExtractionParseError, match="got bool"):
        parse_extraction_response(
            _wrap(
                [
                    {
                        "description": "x",
                        "emotional_impact": True,
                        "emotion_tags": [],
                        "relational_tags": [],
                    }
                ]
            )
        )


def test_parse_unknown_relational_tag_is_dropped_with_warning(caplog):
    caplog.set_level(logging.WARNING, logger="echovessel.prompts.extraction")
    result = parse_extraction_response(
        _wrap(
            [
                {
                    "description": "x",
                    "emotional_impact": 0,
                    "emotion_tags": [],
                    "relational_tags": [
                        "identity-bearing",
                        "made-up-tag",
                        "another-bogus",
                    ],
                }
            ]
        )
    )
    # Unknown tags dropped, known one kept
    assert result.events[0].relational_tags == ["identity-bearing"]
    # Warning logged
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("made-up-tag" in r.getMessage() for r in warnings)
    assert any("another-bogus" in r.getMessage() for r in warnings)


def test_parse_emotion_tags_over_cap_truncated(caplog):
    caplog.set_level(logging.WARNING, logger="echovessel.prompts.extraction")
    result = parse_extraction_response(
        _wrap(
            [
                {
                    "description": "x",
                    "emotional_impact": 0,
                    "emotion_tags": ["a", "b", "c", "d", "e", "f"],
                    "relational_tags": [],
                }
            ]
        )
    )
    assert len(result.events[0].emotion_tags) == MAX_EMOTION_TAGS
    assert result.events[0].emotion_tags == ["a", "b", "c", "d"]
    assert any("truncating to" in r.getMessage() for r in caplog.records)


def test_parse_emotion_tags_non_list_raises():
    with pytest.raises(ExtractionParseError, match="emotion_tags must be a list"):
        parse_extraction_response(
            _wrap(
                [
                    {
                        "description": "x",
                        "emotional_impact": 0,
                        "emotion_tags": "not-a-list",
                        "relational_tags": [],
                    }
                ]
            )
        )


def test_parse_event_not_object_raises():
    with pytest.raises(ExtractionParseError, match=r"events\[0\] must be"):
        parse_extraction_response(json.dumps({"events": ["string-not-object"]}))
