"""WhisperAPIProvider — OpenAI Whisper cloud STT.

Uses `openai.AsyncOpenAI` (already in runtime's [llm] extra — voice does
NOT add a separate openai dependency or API key). Reuses OPENAI_API_KEY
per DISCUSSION.md 2026-04-15 E8.

See docs/voice/01-spec-v0.1.md §4.3.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

from echovessel.voice.base import InputAudioFormat, TranscriptResult
from echovessel.voice.errors import (
    VoiceBudgetError,
    VoicePermanentError,
    VoiceTransientError,
)

log = logging.getLogger(__name__)


#: OpenAI Whisper API hard limit on the audio file size, in bytes.
MAX_AUDIO_SIZE_BYTES: int = 25 * 1024 * 1024


class WhisperAPIProvider:
    """OpenAI Whisper API for STT.

    Zero local inference. All transcription happens server-side. The
    client is lazy-loaded so importing `echovessel.voice` does not pull
    in `openai` for consumers that only use StubVoiceProvider.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "whisper-1",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise VoicePermanentError(
                "WhisperAPIProvider: api_key is empty. "
                "Set OPENAI_API_KEY environment variable."
            )
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "openai SDK not installed. Install the [llm] extra: "
                "`uv sync --extra llm` or `pip install openai>=1.30`."
            ) from e
        self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    # --- Identity --------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "whisper_api"

    @property
    def is_cloud(self) -> bool:
        return True

    # --- STT -------------------------------------------------------

    async def transcribe(
        self,
        audio: bytes | AsyncIterator[bytes],
        *,
        language: str | None = None,
        format: InputAudioFormat = "wav",
    ) -> TranscriptResult:
        audio_bytes = await _collapse_audio(audio)

        if not audio_bytes:
            raise VoicePermanentError(
                "WhisperAPIProvider: audio is empty (no speech detected)"
            )

        # Pre-check size BEFORE touching the network. Spec §4.3.
        if len(audio_bytes) > MAX_AUDIO_SIZE_BYTES:
            raise VoicePermanentError(
                f"audio size {len(audio_bytes)} bytes exceeds Whisper API "
                f"limit of {MAX_AUDIO_SIZE_BYTES} bytes (25 MB)"
            )

        client = self._get_client()
        filename = f"recording.{format}"

        try:
            response = await client.audio.transcriptions.create(  # type: ignore[attr-defined]
                model=self._model,
                file=(filename, audio_bytes),
                language=language,
            )
        except Exception as e:  # noqa: BLE001
            raise _classify_whisper_error(e) from e

        text = getattr(response, "text", "") or ""
        text = text.strip()
        if not text:
            raise VoicePermanentError("no speech detected in audio")

        detected_language = getattr(response, "language", None)
        return TranscriptResult(
            text=text,
            language=detected_language or language,
        )

    # --- Health ----------------------------------------------------

    async def health_check(self) -> bool:
        """Best-effort reachability check.

        We DON'T want to waste a transcription request to probe health,
        so we simply verify that the client can be constructed (api key
        present + SDK importable). A 401 / network outage will surface
        at the first real transcribe() call.
        """
        try:
            self._get_client()
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("WhisperAPIProvider health_check failed: %s", e)
            return False


async def _collapse_audio(
    audio: bytes | AsyncIterator[bytes],
) -> bytes:
    """Turn `bytes | AsyncIterator[bytes]` into a single bytes blob.

    Whisper API is file-upload based and does not support streaming
    input. MVP providers allow the iterator form at the Protocol level
    and internally collapse.
    """
    if isinstance(audio, (bytes, bytearray, memoryview)):
        return bytes(audio)

    chunks: list[bytes] = []
    async for chunk in audio:
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise VoicePermanentError(
                f"audio chunks must be bytes-like, got {type(chunk).__name__}"
            )
        chunks.append(bytes(chunk))
    return b"".join(chunks)


def _classify_whisper_error(e: Exception) -> Exception:
    """Map openai SDK exceptions to the voice error hierarchy.

    Mirrors `runtime/llm/anthropic._classify_anthropic_error` — duck-typed
    on `.status_code` / `.response.status_code` + class name heuristics
    so mocked tests can trigger each branch.
    """
    if isinstance(e, (VoiceTransientError, VoicePermanentError)):
        return e

    status = _extract_status(e)
    cls_name = e.__class__.__name__

    if status is None:
        if any(hint in cls_name for hint in ("Timeout", "Connection", "Network", "APIConnection")):
            return VoiceTransientError(f"{cls_name}: {e}")
        return VoicePermanentError(f"{cls_name}: {e}")

    if status == 429:
        return VoiceTransientError(f"rate limited: {e}")
    if status >= 500:
        return VoiceTransientError(f"server error {status}: {e}")
    if status in (401, 403):
        return VoicePermanentError(f"auth error {status}: {e}")
    if status == 402:
        return VoiceBudgetError(f"budget/quota error {status}: {e}")
    return VoicePermanentError(f"client error {status}: {e}")


def _extract_status(e: Exception) -> int | None:
    status = getattr(e, "status_code", None)
    if status is not None:
        return status
    response = getattr(e, "response", None)
    if response is not None:
        return getattr(response, "status_code", None)
    return None


def build_whisper_api_from_env(
    *,
    api_key_env: str = "OPENAI_API_KEY",
    model: str = "whisper-1",
) -> WhisperAPIProvider:
    """Convenience factory used by `factory.build_voice_service`."""
    api_key = os.environ.get(api_key_env) if api_key_env else None
    return WhisperAPIProvider(api_key=api_key, model=model)


__all__ = [
    "WhisperAPIProvider",
    "MAX_AUDIO_SIZE_BYTES",
    "build_whisper_api_from_env",
]
