"""Tests for voice factory — build_voice_service and sub-factories."""

from __future__ import annotations

from pathlib import Path

import pytest

from echovessel.voice import (
    StubVoiceProvider,
    VoiceService,
    VoiceServiceConfig,
    build_stt_provider,
    build_tts_provider,
    build_voice_service,
)

# ---------------------------------------------------------------------------
# Public API import sanity
# ---------------------------------------------------------------------------


def test_public_api_exports_are_importable():
    """Smoke test: every symbol in `__all__` is importable from the package."""
    import echovessel.voice as voice_mod

    for name in voice_mod.__all__:
        assert hasattr(voice_mod, name), f"voice package missing {name!r}"


# ---------------------------------------------------------------------------
# build_tts_provider
# ---------------------------------------------------------------------------


def test_build_tts_stub():
    tts = build_tts_provider(provider="stub", api_key_env="UNUSED")
    assert isinstance(tts, StubVoiceProvider)
    assert tts.provider_name == "stub"


def test_build_tts_fishaudio(monkeypatch):
    monkeypatch.setenv("FISH_API_KEY_TEST", "fake-key")
    from echovessel.voice.fishaudio import FishAudioProvider

    tts = build_tts_provider(
        provider="fishaudio", api_key_env="FISH_API_KEY_TEST"
    )
    assert isinstance(tts, FishAudioProvider)
    assert tts._api_key == "fake-key"


def test_build_tts_unknown_raises():
    with pytest.raises(ValueError, match="Unknown TTS provider"):
        build_tts_provider(provider="bogus", api_key_env="UNUSED")


# ---------------------------------------------------------------------------
# build_stt_provider
# ---------------------------------------------------------------------------


def test_build_stt_stub():
    stt = build_stt_provider(provider="stub", api_key_env="UNUSED")
    assert isinstance(stt, StubVoiceProvider)


def test_build_stt_whisper_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY_TEST", "sk-test")
    from echovessel.voice.whisper_api import WhisperAPIProvider

    stt = build_stt_provider(
        provider="whisper_api", api_key_env="OPENAI_API_KEY_TEST"
    )
    assert isinstance(stt, WhisperAPIProvider)
    assert stt._api_key == "sk-test"


def test_build_stt_unknown_raises():
    with pytest.raises(ValueError, match="Unknown STT provider"):
        build_stt_provider(provider="bogus", api_key_env="UNUSED")


# ---------------------------------------------------------------------------
# build_voice_service
# ---------------------------------------------------------------------------


def test_build_voice_service_stub_stub():
    cfg = VoiceServiceConfig(
        tts_provider="stub",
        stt_provider="stub",
        tts_api_key_env="UNUSED",
        stt_api_key_env="UNUSED",
    )
    svc = build_voice_service(cfg)

    assert isinstance(svc, VoiceService)
    assert svc.tts_provider_name == "stub"
    assert svc.stt_provider_name == "stub"
    assert svc.is_fully_local is True


def test_build_voice_service_fishaudio_whisper(monkeypatch):
    monkeypatch.setenv("FISH_API_KEY_T", "fake-fish")
    monkeypatch.setenv("OPENAI_API_KEY_T", "sk-fake")

    cfg = VoiceServiceConfig(
        tts_provider="fishaudio",
        stt_provider="whisper_api",
        tts_api_key_env="FISH_API_KEY_T",
        stt_api_key_env="OPENAI_API_KEY_T",
    )
    svc = build_voice_service(cfg)

    assert svc.tts_provider_name == "fishaudio"
    assert svc.stt_provider_name == "whisper_api"
    assert svc.is_fully_local is False


def test_build_voice_service_mixed_fishaudio_stub(monkeypatch):
    """Dev-mode config: real TTS, stub STT (save on Whisper while testing)."""
    monkeypatch.setenv("FISH_API_KEY_T", "fake")

    cfg = VoiceServiceConfig(
        tts_provider="fishaudio",
        stt_provider="stub",
        tts_api_key_env="FISH_API_KEY_T",
        stt_api_key_env="UNUSED",
    )
    svc = build_voice_service(cfg)

    assert svc.tts_provider_name == "fishaudio"
    assert svc.stt_provider_name == "stub"
    assert svc.is_fully_local is False  # TTS is cloud


def test_build_voice_service_propagates_default_voice_id():
    cfg = VoiceServiceConfig(
        tts_provider="stub",
        stt_provider="stub",
        default_voice_id="v_persona_alan",
    )
    svc = build_voice_service(cfg)
    assert svc.default_voice_id == "v_persona_alan"


def test_build_voice_service_without_clone_cache():
    cfg = VoiceServiceConfig(tts_provider="stub", stt_provider="stub")
    svc = build_voice_service(cfg)
    assert svc._clone_cache is None  # type: ignore[attr-defined]


def test_build_voice_service_with_clone_cache(tmp_path: Path):
    cache_path = tmp_path / "voice-cache.json"
    cfg = VoiceServiceConfig(
        tts_provider="stub",
        stt_provider="stub",
        clone_cache_path=cache_path,
    )
    svc = build_voice_service(cfg)
    assert svc._clone_cache is not None  # type: ignore[attr-defined]


def test_build_voice_service_custom_default_format():
    cfg = VoiceServiceConfig(
        tts_provider="stub",
        stt_provider="stub",
        default_audio_format="wav",
    )
    svc = build_voice_service(cfg)
    assert svc.default_format == "wav"


# ---------------------------------------------------------------------------
# End-to-end through the factory with stub
# ---------------------------------------------------------------------------


async def test_factory_built_service_can_speak(tmp_path: Path):
    cfg = VoiceServiceConfig(
        tts_provider="stub",
        stt_provider="stub",
        default_voice_id="v_factory",
        clone_cache_path=tmp_path / "voice-cache.json",
    )
    svc = build_voice_service(cfg)

    chunks: list[bytes] = []
    async for chunk in svc.speak("hello"):
        chunks.append(chunk)

    assert len(chunks) >= 1
    assert b"v_factory" in b"".join(chunks)


async def test_factory_built_service_can_transcribe():
    cfg = VoiceServiceConfig(tts_provider="stub", stt_provider="stub")
    svc = build_voice_service(cfg)

    result = await svc.transcribe(b"audio data")
    assert result.text.startswith("stub-transcript-")


async def test_factory_built_service_can_clone(tmp_path: Path):
    cfg = VoiceServiceConfig(
        tts_provider="stub",
        stt_provider="stub",
        clone_cache_path=tmp_path / "voice-cache.json",
    )
    svc = build_voice_service(cfg)

    entry = await svc.clone_voice_interactive(b"sample", name="factory-voice")
    assert entry.voice_id.startswith("stub-voice-")
    assert entry.name == "factory-voice"

    # And it should be idempotent via the cache
    entry2 = await svc.clone_voice_interactive(b"sample", name="factory-voice")
    assert entry2.voice_id == entry.voice_id
