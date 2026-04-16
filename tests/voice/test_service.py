"""Tests for VoiceService facade."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from echovessel.voice.base import TranscriptResult
from echovessel.voice.cloning import CloneEntry, FingerprintCache, compute_fingerprint
from echovessel.voice.errors import VoicePermanentError, VoiceTransientError
from echovessel.voice.service import VoiceService
from echovessel.voice.stub import StubVoiceProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect(iter_: AsyncIterator[bytes]) -> bytes:
    parts: list[bytes] = []
    async for chunk in iter_:
        parts.append(chunk)
    return b"".join(parts)


def _make_stub_service(
    *,
    default_voice_id: str | None = None,
    clone_cache: FingerprintCache | None = None,
) -> VoiceService:
    stub = StubVoiceProvider()
    return VoiceService(
        tts=stub,
        stt=stub,
        default_voice_id=default_voice_id,
        clone_cache=clone_cache,
    )


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


def test_provider_names_exposed():
    svc = _make_stub_service()
    assert svc.tts_provider_name == "stub"
    assert svc.stt_provider_name == "stub"


def test_is_fully_local_stub():
    svc = _make_stub_service()
    assert svc.is_fully_local is True


def test_is_fully_local_false_with_cloud_tts():
    tts = MagicMock()
    tts.is_cloud = True
    stt = MagicMock()
    stt.is_cloud = False
    svc = VoiceService(tts=tts, stt=stt)
    assert svc.is_fully_local is False


def test_default_voice_id_propagated():
    svc = _make_stub_service(default_voice_id="v_persona")
    assert svc.default_voice_id == "v_persona"


def test_default_format_is_mp3():
    svc = _make_stub_service()
    assert svc.default_format == "mp3"


def test_supports_cloning_from_tts():
    stub = StubVoiceProvider()
    svc = VoiceService(tts=stub, stt=stub)
    assert svc.supports_cloning is True


# ---------------------------------------------------------------------------
# speak() delegation
# ---------------------------------------------------------------------------


async def test_speak_delegates_to_tts_provider():
    svc = _make_stub_service(default_voice_id="v_persona")
    out = await _collect(svc.speak("hello"))
    # Should match stub's deterministic output for ("hello", "v_persona", "mp3")
    stub = StubVoiceProvider()
    expected = await _collect(
        stub.speak("hello", voice_id="v_persona", format="mp3")
    )
    assert out == expected


async def test_speak_explicit_voice_id_overrides_default():
    svc = _make_stub_service(default_voice_id="v_persona")
    out_default = await _collect(svc.speak("hello"))
    out_override = await _collect(svc.speak("hello", voice_id="v_other"))
    assert out_default != out_override


async def test_speak_explicit_format_overrides_default():
    svc = _make_stub_service()
    out_mp3 = await _collect(svc.speak("hello", format="mp3"))
    out_wav = await _collect(svc.speak("hello", format="wav"))
    assert out_mp3 != out_wav


# ---------------------------------------------------------------------------
# transcribe() delegation
# ---------------------------------------------------------------------------


async def test_transcribe_delegates_to_stt():
    svc = _make_stub_service()
    result = await svc.transcribe(b"audio data")
    assert isinstance(result, TranscriptResult)
    assert result.text.startswith("stub-transcript-")


async def test_transcribe_with_language():
    svc = _make_stub_service()
    result = await svc.transcribe(b"audio", language="zh")
    assert result.language == "zh"


async def test_transcribe_with_async_iterator():
    svc = _make_stub_service()

    async def chunks():
        yield b"a"
        yield b"b"

    result = await svc.transcribe(chunks())
    assert result.text.startswith("stub-transcript-")


# ---------------------------------------------------------------------------
# clone_voice_interactive() — full flow
# ---------------------------------------------------------------------------


async def test_clone_voice_interactive_first_call_uploads(tmp_path: Path):
    cache = FingerprintCache(tmp_path / "voice-cache.json")
    svc = _make_stub_service(clone_cache=cache)

    entry = await svc.clone_voice_interactive(b"sample-wav-bytes", name="alan")

    assert isinstance(entry, CloneEntry)
    assert entry.voice_id.startswith("stub-voice-")
    assert entry.name == "alan"
    assert entry.provider == "stub"

    # The cache should have one entry now
    assert len(cache.all_entries()) == 1


async def test_clone_voice_interactive_second_call_is_cache_hit(tmp_path: Path):
    """Same sample twice → same voice_id, provider NOT called second time."""
    cache = FingerprintCache(tmp_path / "voice-cache.json")

    # Wrap stub to count clone_voice calls
    stub = StubVoiceProvider()
    call_count = 0
    original_clone = stub.clone_voice

    async def counting_clone(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original_clone(*args, **kwargs)

    stub.clone_voice = counting_clone  # type: ignore[assignment]
    svc = VoiceService(tts=stub, stt=stub, clone_cache=cache)

    sample = b"identical sample"
    first = await svc.clone_voice_interactive(sample, name="alan")
    second = await svc.clone_voice_interactive(sample, name="alan")

    assert first.voice_id == second.voice_id
    assert call_count == 1, "Cache hit must skip the provider.clone_voice call"


async def test_clone_voice_interactive_different_samples_both_upload(tmp_path: Path):
    cache = FingerprintCache(tmp_path / "voice-cache.json")
    svc = _make_stub_service(clone_cache=cache)

    e1 = await svc.clone_voice_interactive(b"sample one", name="v1")
    e2 = await svc.clone_voice_interactive(b"sample two", name="v2")

    assert e1.voice_id != e2.voice_id
    assert len(cache.all_entries()) == 2


async def test_clone_voice_interactive_without_cache(tmp_path: Path):
    """Works without a cache — just doesn't persist."""
    svc = _make_stub_service(clone_cache=None)
    entry = await svc.clone_voice_interactive(b"data", name="x")
    assert entry.voice_id.startswith("stub-voice-")
    assert entry.fingerprint.startswith("sha256:")


async def test_clone_voice_interactive_from_path(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    sample_file = tmp_path / "sample.wav"
    sample_file.write_bytes(b"path content")

    cache = FingerprintCache(cache_file)
    svc = _make_stub_service(clone_cache=cache)

    entry = await svc.clone_voice_interactive(sample_file, name="alan")
    assert entry.voice_id.startswith("stub-voice-")
    assert entry.fingerprint == compute_fingerprint(b"path content")


async def test_clone_voice_interactive_empty_sample_raises():
    svc = _make_stub_service()
    with pytest.raises(VoicePermanentError, match="empty"):
        await svc.clone_voice_interactive(b"", name="x")


async def test_clone_voice_interactive_provider_without_cloning_raises():
    tts_without_cloning = MagicMock()
    tts_without_cloning.supports_cloning = False
    tts_without_cloning.provider_name = "fake_local"
    svc = VoiceService(tts=tts_without_cloning, stt=MagicMock())

    with pytest.raises(NotImplementedError, match="does not support cloning"):
        await svc.clone_voice_interactive(b"data", name="x")


# ---------------------------------------------------------------------------
# health_check() robustness
# ---------------------------------------------------------------------------


async def test_health_check_both_ok():
    svc = _make_stub_service()
    result = await svc.health_check()
    assert result == {"tts": True, "stt": True}


async def test_health_check_tts_raises_returns_false():
    """A raising health check must not propagate — health_check is
    non-fatal at startup per spec §7.3.1."""
    broken_tts = MagicMock()
    broken_tts.health_check = AsyncMock(side_effect=RuntimeError("dead"))
    healthy_stt = MagicMock()
    healthy_stt.health_check = AsyncMock(return_value=True)

    svc = VoiceService(tts=broken_tts, stt=healthy_stt)
    result = await svc.health_check()
    assert result == {"tts": False, "stt": True}


async def test_health_check_stt_raises_returns_false():
    healthy_tts = MagicMock()
    healthy_tts.health_check = AsyncMock(return_value=True)
    broken_stt = MagicMock()
    broken_stt.health_check = AsyncMock(side_effect=RuntimeError("dead"))

    svc = VoiceService(tts=healthy_tts, stt=broken_stt)
    result = await svc.health_check()
    assert result == {"tts": True, "stt": False}


async def test_health_check_both_fail_does_not_block_daemon():
    """Spec §7.3.1: health_check is non-fatal at startup. Runtime must
    still be able to call it without unhandled exceptions."""
    dead_tts = MagicMock()
    dead_tts.health_check = AsyncMock(side_effect=ValueError("kaboom"))
    dead_stt = MagicMock()
    dead_stt.health_check = AsyncMock(side_effect=ValueError("kaboom"))

    svc = VoiceService(tts=dead_tts, stt=dead_stt)
    result = await svc.health_check()
    assert result == {"tts": False, "stt": False}


# ---------------------------------------------------------------------------
# Cross-provider failure isolation — TTS failure doesn't affect STT
# ---------------------------------------------------------------------------


async def test_tts_failure_does_not_block_stt():
    """Spec §4.2 failure contract: VoiceTransientError on speak must
    surface as-is but transcribe MUST still work on the same service."""
    broken_tts = MagicMock()

    async def _bad_speak(*args, **kwargs):
        raise VoiceTransientError("upstream 503")
        yield b""  # unreachable — makes it an async generator

    broken_tts.speak = _bad_speak
    stub_stt = StubVoiceProvider()

    svc = VoiceService(tts=broken_tts, stt=stub_stt)

    with pytest.raises(VoiceTransientError):
        async for _ in svc.speak("hi"):
            pass

    # STT still works on the same service instance
    result = await svc.transcribe(b"audio")
    assert result.text.startswith("stub-transcript-")
