"""Tests for WhisperAPIProvider.

All OpenAI SDK calls are mocked — the test environment has no network.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from echovessel.voice.base import TranscriptResult
from echovessel.voice.errors import (
    VoiceBudgetError,
    VoicePermanentError,
    VoiceTransientError,
)
from echovessel.voice.whisper_api import (
    MAX_AUDIO_SIZE_BYTES,
    WhisperAPIProvider,
    _classify_whisper_error,
    _collapse_audio,
    build_whisper_api_from_env,
)

# ---------------------------------------------------------------------------
# Identity / lazy import
# ---------------------------------------------------------------------------


def test_provider_name():
    p = WhisperAPIProvider(api_key="sk-fake")
    assert p.provider_name == "whisper_api"


def test_is_cloud():
    p = WhisperAPIProvider(api_key="sk-fake")
    assert p.is_cloud is True


def test_import_is_lazy_top_level_does_not_import_openai():
    """whisper_api.py top-level statements must NOT import openai.

    Docstrings may mention openai; only actual top-level import lines
    are forbidden. We check by walking the AST and looking at
    module-level Import / ImportFrom nodes.
    """
    import ast

    import echovessel.voice.whisper_api as mod

    with open(mod.__file__) as f:
        tree = ast.parse(f.read())

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("openai"), (
                    f"top-level `import {alias.name}` is forbidden "
                    f"(must be lazy inside _get_client)"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or not node.module.startswith("openai"), (
                f"top-level `from {node.module} import ...` is forbidden "
                f"(must be lazy inside _get_client)"
            )


# ---------------------------------------------------------------------------
# Empty / missing api_key
# ---------------------------------------------------------------------------


def test_get_client_without_api_key_raises():
    p = WhisperAPIProvider(api_key=None)
    with pytest.raises(VoicePermanentError, match="api_key is empty"):
        p._get_client()


def test_get_client_with_empty_api_key_raises():
    p = WhisperAPIProvider(api_key="")
    with pytest.raises(VoicePermanentError, match="api_key is empty"):
        p._get_client()


# ---------------------------------------------------------------------------
# _collapse_audio helper
# ---------------------------------------------------------------------------


async def test_collapse_audio_bytes_passthrough():
    result = await _collapse_audio(b"hello")
    assert result == b"hello"


async def test_collapse_audio_iterator():
    async def chunks():
        yield b"a"
        yield b"b"
        yield b"c"

    result = await _collapse_audio(chunks())
    assert result == b"abc"


async def test_collapse_audio_empty_iterator_returns_empty_bytes():
    async def empty():
        if False:
            yield b""

    result = await _collapse_audio(empty())
    assert result == b""


async def test_collapse_audio_non_bytes_chunk_raises():
    async def bad_chunks():
        yield "string not bytes"  # type: ignore[misc]

    with pytest.raises(VoicePermanentError, match="chunks must be bytes-like"):
        await _collapse_audio(bad_chunks())


# ---------------------------------------------------------------------------
# transcribe() — happy path with mocked SDK
# ---------------------------------------------------------------------------


def _make_provider_with_mocked_client(mocked_client):
    p = WhisperAPIProvider(api_key="sk-fake")
    p._client = mocked_client  # inject, bypass lazy import
    return p


async def test_transcribe_returns_text():
    mock_client = MagicMock()
    mock_client.audio = MagicMock()
    mock_client.audio.transcriptions = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="hello world", language="en")
    )

    p = _make_provider_with_mocked_client(mock_client)
    result = await p.transcribe(b"fake audio bytes")

    assert isinstance(result, TranscriptResult)
    assert result.text == "hello world"
    assert result.language == "en"
    mock_client.audio.transcriptions.create.assert_awaited_once()


async def test_transcribe_from_async_iterator():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="transcribed", language=None)
    )

    async def chunks():
        yield b"part1"
        yield b"part2"

    p = _make_provider_with_mocked_client(mock_client)
    result = await p.transcribe(chunks())
    assert result.text == "transcribed"

    # The call should have received concatenated bytes
    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    filename, file_bytes = call_kwargs["file"]
    assert file_bytes == b"part1part2"


async def test_transcribe_passes_language_hint():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="你好", language="zh")
    )

    p = _make_provider_with_mocked_client(mock_client)
    await p.transcribe(b"audio", language="zh")

    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    assert call_kwargs["language"] == "zh"
    assert call_kwargs["model"] == "whisper-1"


async def test_transcribe_passes_format_as_filename_extension():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="x", language=None)
    )

    p = _make_provider_with_mocked_client(mock_client)
    await p.transcribe(b"audio", format="webm")

    call_kwargs = mock_client.audio.transcriptions.create.call_args.kwargs
    filename, _ = call_kwargs["file"]
    assert filename == "recording.webm"


async def test_transcribe_falls_back_to_language_hint_when_sdk_omits():
    """Some whisper responses don't include a .language field."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="hello")  # no .language
    )

    p = _make_provider_with_mocked_client(mock_client)
    r = await p.transcribe(b"audio", language="en")
    assert r.language == "en"


# ---------------------------------------------------------------------------
# transcribe() — failure paths
# ---------------------------------------------------------------------------


async def test_transcribe_empty_audio_raises_before_network():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock()

    p = _make_provider_with_mocked_client(mock_client)
    with pytest.raises(VoicePermanentError, match="no speech detected"):
        await p.transcribe(b"")

    mock_client.audio.transcriptions.create.assert_not_called()


async def test_transcribe_oversize_raises_before_network():
    """25 MB pre-check MUST raise before touching the network."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock()

    p = _make_provider_with_mocked_client(mock_client)
    big_audio = b"x" * (MAX_AUDIO_SIZE_BYTES + 1)
    with pytest.raises(VoicePermanentError, match="exceeds Whisper API limit"):
        await p.transcribe(big_audio)

    mock_client.audio.transcriptions.create.assert_not_called()


async def test_transcribe_at_size_boundary_passes():
    """Exactly 25 MB should pass the pre-check."""
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="boundary ok", language=None)
    )

    p = _make_provider_with_mocked_client(mock_client)
    big_audio = b"x" * MAX_AUDIO_SIZE_BYTES
    r = await p.transcribe(big_audio)
    assert r.text == "boundary ok"


async def test_transcribe_empty_response_raises():
    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        return_value=SimpleNamespace(text="   ", language=None)
    )

    p = _make_provider_with_mocked_client(mock_client)
    with pytest.raises(VoicePermanentError, match="no speech detected"):
        await p.transcribe(b"audio")


async def test_transcribe_server_error_maps_to_transient():
    class FakeSDKError(Exception):
        status_code = 503

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        side_effect=FakeSDKError("upstream")
    )

    p = _make_provider_with_mocked_client(mock_client)
    with pytest.raises(VoiceTransientError, match="server error 503"):
        await p.transcribe(b"audio")


async def test_transcribe_auth_error_maps_to_permanent():
    class FakeAuthError(Exception):
        status_code = 401

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        side_effect=FakeAuthError("invalid key")
    )

    p = _make_provider_with_mocked_client(mock_client)
    with pytest.raises(VoicePermanentError, match="auth error 401"):
        await p.transcribe(b"audio")


async def test_transcribe_quota_error_maps_to_budget():
    class FakeQuotaError(Exception):
        status_code = 402

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        side_effect=FakeQuotaError("quota exceeded")
    )

    p = _make_provider_with_mocked_client(mock_client)
    with pytest.raises(VoiceBudgetError, match="budget"):
        await p.transcribe(b"audio")


async def test_transcribe_rate_limit_maps_to_transient():
    class FakeRateLimitError(Exception):
        status_code = 429

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        side_effect=FakeRateLimitError("slow down")
    )

    p = _make_provider_with_mocked_client(mock_client)
    with pytest.raises(VoiceTransientError, match="rate limited"):
        await p.transcribe(b"audio")


async def test_transcribe_connection_error_maps_to_transient():
    class APIConnectionError(Exception):
        pass

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create = AsyncMock(
        side_effect=APIConnectionError("dns failure")
    )

    p = _make_provider_with_mocked_client(mock_client)
    with pytest.raises(VoiceTransientError, match="APIConnectionError"):
        await p.transcribe(b"audio")


# ---------------------------------------------------------------------------
# Error classifier unit tests
# ---------------------------------------------------------------------------


def test_classify_voice_errors_passed_through():
    err = VoiceTransientError("already classified")
    assert _classify_whisper_error(err) is err

    err2 = VoicePermanentError("already classified")
    assert _classify_whisper_error(err2) is err2


def test_classify_via_response_attribute():
    class SDKError(Exception):
        def __init__(self, status):
            super().__init__("sdk")
            self.response = SimpleNamespace(status_code=status)

    assert isinstance(_classify_whisper_error(SDKError(500)), VoiceTransientError)
    assert isinstance(_classify_whisper_error(SDKError(401)), VoicePermanentError)
    assert isinstance(_classify_whisper_error(SDKError(402)), VoiceBudgetError)


def test_classify_unknown_error_defaults_to_permanent():
    class RandomError(Exception):
        pass

    result = _classify_whisper_error(RandomError("mystery"))
    assert isinstance(result, VoicePermanentError)


# ---------------------------------------------------------------------------
# build_whisper_api_from_env
# ---------------------------------------------------------------------------


def test_build_from_env_reads_environment_variable(monkeypatch):
    monkeypatch.setenv("CUSTOM_KEY_VAR", "sk-from-env")
    p = build_whisper_api_from_env(api_key_env="CUSTOM_KEY_VAR")
    assert p._api_key == "sk-from-env"


def test_build_from_env_missing_variable_is_none(monkeypatch):
    monkeypatch.delenv("MISSING_KEY_VAR", raising=False)
    p = build_whisper_api_from_env(api_key_env="MISSING_KEY_VAR")
    assert p._api_key is None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


async def test_health_check_with_valid_key(monkeypatch):
    """Health check should just verify client construction works.
    We inject a fake openai module to avoid a real import requirement."""
    import sys
    import types

    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = lambda **kw: MagicMock()
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    p = WhisperAPIProvider(api_key="sk-fake")
    assert await p.health_check() is True


async def test_health_check_without_key_returns_false():
    p = WhisperAPIProvider(api_key=None)
    assert await p.health_check() is False
