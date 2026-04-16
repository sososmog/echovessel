"""Voice cloning idempotency — FingerprintCache + helpers.

Spec reference: docs/voice/01-spec-v0.1.md §5 (Voice Cloning Flow).

The goal is simple: running `echovessel voice clone sample.wav` twice on
the same file MUST return the same voice_id and skip the second upload.

Implementation: local JSON cache at `~/.echovessel/voice-cache.json`
keyed by a stable fingerprint of the sample bytes. Atomic writes via
tmp file + rename. Corrupted cache files are renamed aside and the
cache starts fresh without crashing the CLI.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fingerprint computation
# ---------------------------------------------------------------------------


def compute_fingerprint(sample_bytes: bytes) -> str:
    """Compute a stable fingerprint for a voice sample.

    Spec §5.1 step 4 originally defined this as
    ``sha256 + ":" + size + ":" + duration``. MVP can't compute duration
    without an audio parser, so we use ``sha256 + ":" + size``. If
    duration is added later we bump the version prefix.

    Format: ``sha256:<hex>:<size>``
    """
    if not sample_bytes:
        raise ValueError("compute_fingerprint: sample_bytes is empty")
    digest = hashlib.sha256(sample_bytes).hexdigest()
    size = len(sample_bytes)
    return f"sha256:{digest}:{size}"


# ---------------------------------------------------------------------------
# CloneEntry value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CloneEntry:
    """A single record in the voice-clone cache."""

    voice_id: str
    name: str
    provider: str
    created_at: str  # ISO 8601 UTC
    fingerprint: str

    def to_json_dict(self) -> dict[str, str]:
        return {
            "voice_id": self.voice_id,
            "name": self.name,
            "provider": self.provider,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_json_dict(fingerprint: str, data: dict[str, str]) -> CloneEntry:
        return CloneEntry(
            voice_id=str(data.get("voice_id", "")),
            name=str(data.get("name", "")),
            provider=str(data.get("provider", "")),
            created_at=str(data.get("created_at", "")),
            fingerprint=fingerprint,
        )


# ---------------------------------------------------------------------------
# FingerprintCache
# ---------------------------------------------------------------------------


class FingerprintCache:
    """Persistent fingerprint → CloneEntry cache for voice-clone idempotency.

    File format (at `path`):

        {
          "sha256:<hex>:<size>": {
            "voice_id": "fishmodel_xxx",
            "name": "alan-voice",
            "provider": "fishaudio",
            "created_at": "2026-04-15T10:30:00Z"
          },
          ...
        }

    Thread safety: not guaranteed. MVP CLI usage is single-threaded.
    Runtime voice code paths do not write the cache — cloning is a
    user-initiated offline operation.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._data: dict[str, dict[str, str]] = {}
        self._loaded = False

    # --- Load / save ------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        if not self._path.exists():
            self._data = {}
            return

        try:
            raw = self._path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("voice-cache.json is not a JSON object")
            self._data = {
                str(k): dict(v) for k, v in parsed.items() if isinstance(v, dict)
            }
        except (json.JSONDecodeError, ValueError, OSError) as e:
            corrupted_name = (
                self._path.stem
                + f".corrupted-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
                + self._path.suffix
            )
            corrupted_path = self._path.with_name(corrupted_name)
            log.warning(
                "voice-cache.json is corrupted (%s); moving to %s and starting fresh",
                e,
                corrupted_path,
            )
            try:
                self._path.rename(corrupted_path)
            except OSError as rename_error:
                log.warning("failed to rename corrupted cache: %s", rename_error)
            self._data = {}

    def _write_atomic(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(self._path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp_path.replace(self._path)

    # --- Public API -----------------------------------------------

    def lookup(self, fingerprint: str) -> CloneEntry | None:
        """Return the cached CloneEntry for this fingerprint, or None."""
        self._ensure_loaded()
        raw = self._data.get(fingerprint)
        if raw is None:
            return None
        return CloneEntry.from_json_dict(fingerprint, raw)

    def store(
        self,
        fingerprint: str,
        *,
        voice_id: str,
        name: str,
        provider: str,
    ) -> CloneEntry:
        """Store a new entry for this fingerprint.

        If an entry already exists:
          - If it matches the incoming values, the existing entry is
            returned unchanged.
          - If the `name` differs, a warning is logged and the ORIGINAL
            entry is returned (first-write-wins). This preserves the
            idempotence guarantee: same fingerprint always returns the
            same voice_id even if the user tried to re-clone with a new
            label.
        """
        self._ensure_loaded()
        existing = self._data.get(fingerprint)
        if existing is not None:
            existing_entry = CloneEntry.from_json_dict(fingerprint, existing)
            if existing_entry.name != name:
                log.warning(
                    "fingerprint %s already cached as %r (voice_id=%s); "
                    "not re-uploading with new name %r",
                    fingerprint[:32],
                    existing_entry.name,
                    existing_entry.voice_id,
                    name,
                )
            return existing_entry

        created_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_entry = {
            "voice_id": voice_id,
            "name": name,
            "provider": provider,
            "created_at": created_at,
        }
        self._data[fingerprint] = new_entry
        self._write_atomic()
        return CloneEntry(
            voice_id=voice_id,
            name=name,
            provider=provider,
            created_at=created_at,
            fingerprint=fingerprint,
        )

    def all_entries(self) -> list[CloneEntry]:
        """Return all cached entries. Useful for `echovessel voice list`."""
        self._ensure_loaded()
        return [
            CloneEntry.from_json_dict(fp, data)
            for fp, data in self._data.items()
        ]

    def clear(self) -> None:
        """Delete all cached entries. Writes an empty file."""
        self._ensure_loaded()
        self._data = {}
        self._write_atomic()


__all__ = [
    "compute_fingerprint",
    "CloneEntry",
    "FingerprintCache",
]
