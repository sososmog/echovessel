"""Tests for StubVoiceProvider — determinism, double-sided, and edge cases."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from echovessel.voice.base import TranscriptResult, VoiceMeta
from echovessel.voice.errors import VoicePermanentError
from echovessel.voice.stub import StubVoiceProvider

# ---------------------------------------------------------------------------
# Identity / capability
# ---------------------------------------------------------------------------


def test_stub_provider_name():
    stub = StubVoiceProvider()
    assert stub.provider_name == "stub"


def test_stub_is_not_cloud():
    stub = StubVoiceProvider()
    assert stub.is_cloud is False


def test_stub_supports_cloning():
    stub = StubVoiceProvider()
    assert stub.supports_cloning is True


async def test_stub_health_check():
    stub = StubVoiceProvider()
    assert await stub.health_check() is True


# ---------------------------------------------------------------------------
# TTS — speak()
# ---------------------------------------------------------------------------


async def _collect(iter_: AsyncIterator[bytes]) -> bytes:
    parts: list[bytes] = []
    async for chunk in iter_:
        parts.append(chunk)
    return b"".join(parts)


async def test_speak_yields_deterministic_bytes():
    stub = StubVoiceProvider()
    out1 = await _collect(stub.speak("hello"))
    out2 = await _collect(stub.speak("hello"))
    assert out1 == out2, "Stub speak must be deterministic for same input"
    assert len(out1) > 0


async def test_speak_different_text_different_bytes():
    stub = StubVoiceProvider()
    out_a = await _collect(stub.speak("hello"))
    out_b = await _collect(stub.speak("world"))
    assert out_a != out_b


async def test_speak_different_voice_id_different_bytes():
    stub = StubVoiceProvider()
    out_a = await _collect(stub.speak("hello", voice_id="voice-a"))
    out_b = await _collect(stub.speak("hello", voice_id="voice-b"))
    assert out_a != out_b


async def test_speak_different_format_different_bytes():
    stub = StubVoiceProvider()
    out_mp3 = await _collect(stub.speak("hello", format="mp3"))
    out_wav = await _collect(stub.speak("hello", format="wav"))
    assert out_mp3 != out_wav


async def test_speak_empty_text_raises():
    stub = StubVoiceProvider()
    with pytest.raises(ValueError, match="non-empty"):
        async for _ in stub.speak(""):
            pass


# ---------------------------------------------------------------------------
# TTS — clone_voice()
# ---------------------------------------------------------------------------


async def test_clone_voice_returns_deterministic_id():
    stub = StubVoiceProvider()
    sample = b"fake wav data"
    id1 = await stub.clone_voice(sample, name="alan-voice")
    id2 = await stub.clone_voice(sample, name="alan-voice")
    assert id1 == id2, "Same sample + same name must return same id"
    assert id1.startswith("stub-voice-")


async def test_clone_voice_different_samples_different_ids():
    stub = StubVoiceProvider()
    id1 = await stub.clone_voice(b"sample one", name="x")
    id2 = await stub.clone_voice(b"sample two", name="x")
    assert id1 != id2


async def test_clone_voice_different_names_different_ids():
    stub = StubVoiceProvider()
    sample = b"identical sample"
    id1 = await stub.clone_voice(sample, name="voice-a")
    id2 = await stub.clone_voice(sample, name="voice-b")
    assert id1 != id2


async def test_clone_voice_from_path(tmp_path):
    stub = StubVoiceProvider()
    sample_path = tmp_path / "sample.wav"
    sample_path.write_bytes(b"content")
    voice_id = await stub.clone_voice(sample_path, name="path-voice")
    assert voice_id.startswith("stub-voice-")


async def test_clone_voice_empty_sample_raises():
    stub = StubVoiceProvider()
    with pytest.raises(VoicePermanentError, match="sample is empty"):
        await stub.clone_voice(b"", name="x")


# ---------------------------------------------------------------------------
# TTS — list_voices()
# ---------------------------------------------------------------------------


async def test_list_voices_returns_at_least_one():
    stub = StubVoiceProvider()
    voices = await stub.list_voices()
    assert len(voices) >= 1
    assert all(isinstance(v, VoiceMeta) for v in voices)
    assert voices[0].provider_name == "stub"


async def test_list_voices_custom_default_id():
    stub = StubVoiceProvider(voice_id="custom-id")
    voices = await stub.list_voices()
    assert voices[0].voice_id == "custom-id"


# ---------------------------------------------------------------------------
# STT — transcribe()
# ---------------------------------------------------------------------------


async def test_transcribe_deterministic_bytes_input():
    stub = StubVoiceProvider()
    r1 = await stub.transcribe(b"audio data")
    r2 = await stub.transcribe(b"audio data")
    assert r1.text == r2.text
    assert r1.text.startswith("stub-transcript-")


async def test_transcribe_different_audio_different_text():
    stub = StubVoiceProvider()
    r1 = await stub.transcribe(b"audio one")
    r2 = await stub.transcribe(b"audio two")
    assert r1.text != r2.text


async def test_transcribe_async_iterator_input():
    stub = StubVoiceProvider()

    async def chunks():
        yield b"part1"
        yield b"part2"
        yield b"part3"

    r = await stub.transcribe(chunks())
    assert r.text.startswith("stub-transcript-")

    # And the concatenated form should produce the same result
    r_bytes = await stub.transcribe(b"part1part2part3")
    assert r.text == r_bytes.text


async def test_transcribe_empty_audio_raises():
    stub = StubVoiceProvider()
    with pytest.raises(VoicePermanentError, match="no speech detected"):
        await stub.transcribe(b"")


async def test_transcribe_empty_iterator_raises():
    stub = StubVoiceProvider()

    async def empty():
        if False:
            yield b""

    with pytest.raises(VoicePermanentError, match="no speech detected"):
        await stub.transcribe(empty())


async def test_transcribe_returns_transcript_result_type():
    stub = StubVoiceProvider()
    r = await stub.transcribe(b"audio")
    assert isinstance(r, TranscriptResult)


async def test_transcribe_language_hint_passed_through():
    stub = StubVoiceProvider()
    r = await stub.transcribe(b"audio", language="zh")
    assert r.language == "zh"
