"""StubVoiceProvider — deterministic in-process provider for tests / dry-run.

This is the ONLY class in the voice module that satisfies BOTH TTSProvider
and STTProvider (spec §4.4). It exists purely so that Voice code paths
can be exercised without network, without SDKs, and without API keys.

Rules:
- Zero network
- Zero SDK dependency
- Same input → same output (hash-based)
- Raises VoicePermanentError for empty-audio transcribe (matching the
  real providers' "no speech detected" contract)

See docs/voice/01-spec-v0.1.md §4.4 for the spec reference and §4.4's
"what time use it" list.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

from echovessel.voice.base import (
    AudioFormat,
    InputAudioFormat,
    TranscriptResult,
    VoiceMeta,
)
from echovessel.voice.errors import VoicePermanentError

_DEFAULT_STUB_VOICE_ID = "stub-voice"


class StubVoiceProvider:
    """Double-sided stub: implements both TTSProvider and STTProvider.

    Constructors may customize the default voice id for tests that need
    multiple distinct stub "voices".
    """

    def __init__(self, *, voice_id: str = _DEFAULT_STUB_VOICE_ID) -> None:
        self._voice_id = voice_id

    # --- Identity / capability (TTS side) -------------------------

    @property
    def provider_name(self) -> str:
        return "stub"

    @property
    def is_cloud(self) -> bool:
        return False

    @property
    def supports_cloning(self) -> bool:
        # True because clone_voice() returns a deterministic id. Real
        # cloning is NOT happening, but the API contract is honored.
        return True

    # --- TTS ------------------------------------------------------

    async def speak(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        format: AudioFormat = "mp3",
    ) -> AsyncIterator[bytes]:
        """Yield a deterministic "audio" byte blob derived from the input.

        The bytes are not valid audio — they're a canonical encoding used
        so that tests can assert "same input → same bytes" without
        worrying about actual decoding.
        """
        if not text:
            raise ValueError("StubVoiceProvider.speak: text must be non-empty")

        effective_voice = (voice_id or self._voice_id).encode("utf-8")
        fmt_tag = format.encode("utf-8")
        text_digest = hashlib.sha1(text.encode("utf-8")).digest()[:8]
        yield b"STUB-" + fmt_tag + b"-" + text_digest + b"-" + effective_voice

    async def clone_voice(
        self,
        sample: bytes | Path,
        *,
        name: str,
    ) -> str:
        """Return a deterministic id derived from the sample bytes.

        `name` is included in the hash input so that renaming a clone
        produces a different id (simplifies tests that want to distinguish
        two clones of the same sample).
        """
        sample_bytes = sample.read_bytes() if isinstance(sample, Path) else sample

        if not sample_bytes:
            raise VoicePermanentError("StubVoiceProvider.clone_voice: sample is empty")

        digest = hashlib.sha1(sample_bytes + b"|" + name.encode("utf-8")).hexdigest()[:12]
        return f"stub-voice-{digest}"

    async def list_voices(self) -> list[VoiceMeta]:
        return [
            VoiceMeta(
                voice_id=self._voice_id,
                display_name="Stub Voice",
                provider_name="stub",
                language="en",
                preview_url=None,
            ),
        ]

    # --- STT ------------------------------------------------------

    async def transcribe(
        self,
        audio: bytes | AsyncIterator[bytes],
        *,
        language: str | None = None,
        format: InputAudioFormat = "wav",
    ) -> TranscriptResult:
        if isinstance(audio, bytes):
            audio_bytes = audio
        else:
            chunks: list[bytes] = []
            async for chunk in audio:
                chunks.append(chunk)
            audio_bytes = b"".join(chunks)

        if not audio_bytes:
            raise VoicePermanentError(
                "StubVoiceProvider.transcribe: audio is empty (no speech detected)"
            )

        digest = hashlib.sha1(audio_bytes).hexdigest()[:12]
        return TranscriptResult(
            text=f"stub-transcript-{digest}",
            language=language or "und",
        )

    # --- Health ---------------------------------------------------

    async def health_check(self) -> bool:
        return True


__all__ = ["StubVoiceProvider"]
