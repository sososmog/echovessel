"""TTSProvider and STTProvider Protocols + shared value types.

Voice is a Layer 2 module. This file is the only place the Protocols are
declared — concrete providers (`fishaudio.py`, `whisper_api.py`, `stub.py`)
implement them structurally via `@runtime_checkable`.

Spec references:
- docs/voice/01-spec-v0.1.md §2 (TTSProvider Protocol)
- docs/voice/01-spec-v0.1.md §3 (STTProvider Protocol)
- docs/voice/01-spec-v0.1.md §1.2 (Layer 2 import rules — enforced by CI)

Why two Protocols and not one combined `VoiceProvider`:

    FishAudio does TTS + cloning but NOT STT.
    Whisper API does STT but NOT TTS.

    A combined Protocol would force half the methods to be empty on each
    real provider. See DISCUSSION.md 2026-04-15 E3 for the decision record.

The one exception that implements BOTH Protocols is StubVoiceProvider,
used only in tests and dry-run code paths.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Audio format literals
# ---------------------------------------------------------------------------


AudioFormat = Literal["mp3", "wav", "pcm16"]
"""Supported output formats for TTS.

- mp3 is the MVP default because Web channel ships it straight to an
  HTML <audio> element.
- wav is convenient for debugging and for saving samples.
- pcm16 is 16-bit little-endian PCM at 44.1 kHz mono — useful for future
  WebAudio pipelines and real-time streaming (v1.0).
"""


InputAudioFormat = Literal["mp3", "wav", "pcm16", "webm", "m4a", "ogg"]
"""Broader format set for STT input. Browser MediaRecorder typically outputs
WebM or WAV, mobile recordings are often M4A, voice notes on Discord are
OGG. Providers that can't handle a given format MUST raise
VoicePermanentError with a clear message — do not silently coerce.
"""


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VoiceMeta:
    """Metadata for a single voice / reference model known to a provider.

    Returned by `TTSProvider.list_voices()`. Runtime only persists
    `voice_id` in persona config. The other fields are for UI-side voice
    pickers and for logging.
    """

    voice_id: str
    display_name: str
    provider_name: str
    language: str | None = None
    preview_url: str | None = None


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    """Output of `STTProvider.transcribe()`.

    MVP shape is intentionally minimal: just text plus detected language.
    Segment / word-level timestamps and confidence are v1.0 additions —
    when they land, they'll be added as additional optional fields so
    existing call sites don't break.
    """

    text: str
    language: str | None = None


# ---------------------------------------------------------------------------
# TTSProvider Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class TTSProvider(Protocol):
    """Async text-to-speech provider.

    All methods are async. Implementations MUST NOT block the event loop:
    HTTP I/O uses `httpx.AsyncClient` or equivalent, and the ONLY legal
    exception is `fish-audio-sdk` which is sync-only and must be wrapped
    in `asyncio.to_thread(...)` (spec §4.2 / §11.8).
    """

    # --- Identity / capability ------------------------------------

    @property
    def provider_name(self) -> str:
        """One of 'fishaudio' / 'fishaudio_local' / 'stub'. Stable opaque
        label used in audit logs and config."""
        ...

    @property
    def is_cloud(self) -> bool:
        """True if `speak()` or `clone_voice()` sends data off-machine.
        Runtime uses this to build the local-first startup disclosure."""
        ...

    @property
    def supports_cloning(self) -> bool:
        """True iff `clone_voice()` is implemented. STT-only providers
        trivially would set this False — but the STT-only case is
        STTProvider, not TTSProvider, so the flag is always meaningful
        on a real TTSProvider."""
        ...

    # --- Synthesis ------------------------------------------------

    def speak(
        self,
        text: str,
        *,
        voice_id: str | None = None,
        format: AudioFormat = "mp3",
    ) -> AsyncIterator[bytes]:
        """Synthesize `text` to audio and yield bytes in chunks.

        Callers iterate:

            async for chunk in provider.speak(text, voice_id="v_xx"):
                await sink.write(chunk)

        MVP providers that read the full response before yielding (no
        incremental network stream) MUST still expose this as an async
        iterator. The signature is preserved for forward-compatibility
        with v1.0 real streaming providers.

        Errors:
            ValueError          if `text` is empty (raised at call
                                time, before the iterator yields)
            VoiceTransientError 5xx / timeout / rate limit
            VoicePermanentError 4xx / auth / invalid voice_id
            VoiceBudgetError    402 / quota exceeded
        """
        ...

    # --- Cloning --------------------------------------------------

    async def clone_voice(
        self,
        sample: bytes | Path,
        *,
        name: str,
    ) -> str:
        """Upload `sample` as a reference model, return the voice_id.

        `sample` may be raw bytes or a filesystem path. `name` is a
        human-readable label for list_voices() output, NOT the voice_id.

        Idempotence is NOT enforced at this level — the CLI flow (via
        `VoiceService.clone_voice_interactive`) wraps this with a local
        fingerprint cache for idempotency. Spec §5.2.

        Raises NotImplementedError if `supports_cloning` is False.
        """
        ...

    async def list_voices(self) -> list[VoiceMeta]:
        """Return voices known to this provider (built-in + user-uploaded
        reference models).

        Called lazily by CLI and Web voice pickers, never in the hot
        per-turn path.
        """
        ...

    # --- Health ---------------------------------------------------

    async def health_check(self) -> bool:
        """Cheapest reachability check. Runtime calls this at startup
        (non-fatal: a failing health check logs a warning but does not
        abort the daemon)."""
        ...


# ---------------------------------------------------------------------------
# STTProvider Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class STTProvider(Protocol):
    """Async speech-to-text provider.

    Same blocking-I/O prohibition as TTSProvider. STT has no "voice"
    concept and no "cloning" concept — it only does `audio → text`.
    """

    # --- Identity -------------------------------------------------

    @property
    def provider_name(self) -> str:
        """One of 'whisper_api' / 'whisper_local' / 'stub'."""
        ...

    @property
    def is_cloud(self) -> bool:
        """True if `transcribe()` sends audio off-machine."""
        ...

    # --- Transcription --------------------------------------------

    async def transcribe(
        self,
        audio: bytes | AsyncIterator[bytes],
        *,
        language: str | None = None,
        format: InputAudioFormat = "wav",
    ) -> TranscriptResult:
        """Transcribe `audio` to text.

        `audio` may be raw bytes OR an async iterator of byte chunks. MVP
        providers MUST accept both shapes; they MAY internally concatenate
        iterators to bytes before sending (OpenAI Whisper API requires a
        full file upload).

        `language` is an optional BCP-47 / ISO-639-1 hint.

        `format` tells the provider the container/encoding of the bytes.

        MUST NOT return `text=""` on success. If the audio was silent /
        contained no speech, raise `VoicePermanentError` with a clear
        "no speech detected" message.

        Size limits: OpenAI Whisper API caps at 25 MB — providers MUST
        pre-check and raise `VoicePermanentError` BEFORE touching the
        network.
        """
        ...

    # --- Health ---------------------------------------------------

    async def health_check(self) -> bool:
        """Cheapest reachability check."""
        ...


__all__ = [
    "AudioFormat",
    "InputAudioFormat",
    "VoiceMeta",
    "TranscriptResult",
    "TTSProvider",
    "STTProvider",
]
