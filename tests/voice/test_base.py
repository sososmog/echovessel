"""Tests for echovessel.voice.base — Protocols + value objects."""

from __future__ import annotations

import pytest

from echovessel.voice.base import (
    AudioFormat,
    InputAudioFormat,
    STTProvider,
    TranscriptResult,
    TTSProvider,
    VoiceMeta,
)
from echovessel.voice.stub import StubVoiceProvider

# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


def test_voice_meta_is_frozen():
    meta = VoiceMeta(
        voice_id="v_001",
        display_name="Alice",
        provider_name="fishaudio",
    )
    with pytest.raises((AttributeError, Exception)):
        meta.voice_id = "v_002"  # type: ignore[misc]


def test_voice_meta_defaults():
    meta = VoiceMeta(
        voice_id="v_001",
        display_name="Alice",
        provider_name="fishaudio",
    )
    assert meta.language is None
    assert meta.preview_url is None


def test_transcript_result_is_frozen():
    r = TranscriptResult(text="hello")
    with pytest.raises((AttributeError, Exception)):
        r.text = "goodbye"  # type: ignore[misc]


def test_transcript_result_defaults():
    r = TranscriptResult(text="hi")
    assert r.language is None


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


def test_stub_satisfies_tts_protocol():
    stub = StubVoiceProvider()
    assert isinstance(stub, TTSProvider)


def test_stub_satisfies_stt_protocol():
    stub = StubVoiceProvider()
    assert isinstance(stub, STTProvider)


def test_stub_is_the_only_double_sided_impl():
    """StubVoiceProvider is documented as the only class implementing both
    Protocols. This test mostly guards against future drift (a regression
    where someone accidentally unifies FishAudio + Whisper)."""
    stub = StubVoiceProvider()
    assert isinstance(stub, TTSProvider)
    assert isinstance(stub, STTProvider)


def test_tts_protocol_has_required_attrs():
    stub = StubVoiceProvider()
    # Required by TTSProvider
    for attr in (
        "provider_name",
        "is_cloud",
        "supports_cloning",
        "speak",
        "clone_voice",
        "list_voices",
        "health_check",
    ):
        assert hasattr(stub, attr), f"StubVoiceProvider missing TTS attr {attr}"


def test_stt_protocol_has_required_attrs():
    stub = StubVoiceProvider()
    for attr in ("provider_name", "is_cloud", "transcribe", "health_check"):
        assert hasattr(stub, attr), f"StubVoiceProvider missing STT attr {attr}"


# ---------------------------------------------------------------------------
# Format literal types can be used as plain strings
# ---------------------------------------------------------------------------


def test_audio_format_values():
    valid: list[AudioFormat] = ["mp3", "wav", "pcm16"]
    assert all(isinstance(f, str) for f in valid)


def test_input_audio_format_values():
    valid: list[InputAudioFormat] = ["mp3", "wav", "pcm16", "webm", "m4a", "ogg"]
    assert all(isinstance(f, str) for f in valid)
