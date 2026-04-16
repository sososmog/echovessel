"""JSON conversation arrays are flattened into chunk-friendly text."""

from __future__ import annotations

import json

from echovessel.import_.normalization import normalize_bytes


def test_conversation_array_flattens_per_element():
    data = [
        {"speaker": "me", "ts": "2024-06-14 22:41", "text": "我去了 Mochi 的窗户下面"},
        {"speaker": "me", "ts": "2024-06-14 22:42", "text": "她走之后那里没人去"},
    ]
    raw = json.dumps(data, ensure_ascii=False).encode()
    out = normalize_bytes(raw, suffix=".json")
    # Each conversation element should appear in the output
    assert "我去了 Mochi 的窗户下面" in out
    assert "她走之后那里没人去" in out
    # And speakers/timestamps preserved as key/value lines
    assert "speaker: me" in out
    assert "ts: 2024-06-14 22:41" in out
    # There should be at least one blank line separating elements
    assert "\n\n" in out


def test_persona_object_flattens_as_single_block():
    data = {"name": "Anna", "traits": {"mood": "quiet", "fear": "loss"}}
    raw = json.dumps(data).encode()
    out = normalize_bytes(raw, suffix=".json")
    assert "name: Anna" in out
    assert "traits.mood: quiet" in out
    assert "traits.fear: loss" in out
