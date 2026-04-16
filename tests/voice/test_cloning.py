"""Tests for FingerprintCache + compute_fingerprint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echovessel.voice.cloning import (
    CloneEntry,
    FingerprintCache,
    compute_fingerprint,
)

# ---------------------------------------------------------------------------
# compute_fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable():
    """Same bytes must produce same fingerprint."""
    data = b"the quick brown fox"
    fp1 = compute_fingerprint(data)
    fp2 = compute_fingerprint(data)
    assert fp1 == fp2


def test_fingerprint_includes_sha256_and_size():
    data = b"abc"
    fp = compute_fingerprint(data)
    assert fp.startswith("sha256:")
    assert fp.endswith(":3")  # len(b"abc") == 3


def test_different_bytes_different_fingerprints():
    fp1 = compute_fingerprint(b"hello")
    fp2 = compute_fingerprint(b"world")
    assert fp1 != fp2


def test_same_length_different_content_different_fingerprints():
    """Two 10-byte samples that differ should have different fingerprints
    — SHA-256 catches the content difference even when size matches."""
    fp1 = compute_fingerprint(b"aaaaaaaaaa")
    fp2 = compute_fingerprint(b"aaaaabbbbb")
    assert fp1 != fp2


def test_empty_sample_raises():
    with pytest.raises(ValueError, match="empty"):
        compute_fingerprint(b"")


# ---------------------------------------------------------------------------
# FingerprintCache — basic lookup / store
# ---------------------------------------------------------------------------


def test_lookup_returns_none_for_missing(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)
    assert cache.lookup("sha256:nope:0") is None


def test_store_then_lookup(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)

    entry = cache.store(
        "sha256:abc:100",
        voice_id="fishmodel_xyz",
        name="alan-voice",
        provider="fishaudio",
    )

    assert isinstance(entry, CloneEntry)
    assert entry.voice_id == "fishmodel_xyz"

    hit = cache.lookup("sha256:abc:100")
    assert hit is not None
    assert hit.voice_id == "fishmodel_xyz"
    assert hit.name == "alan-voice"
    assert hit.provider == "fishaudio"
    assert hit.fingerprint == "sha256:abc:100"
    assert hit.created_at.endswith("Z")  # UTC ISO


def test_store_creates_file_on_disk(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)
    cache.store("sha256:xx:10", voice_id="v1", name="n1", provider="p1")

    assert cache_file.exists()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "sha256:xx:10" in data
    assert data["sha256:xx:10"]["voice_id"] == "v1"


# ---------------------------------------------------------------------------
# Persistence — new instance sees previous data
# ---------------------------------------------------------------------------


def test_persistence_across_instances(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"

    cache1 = FingerprintCache(cache_file)
    cache1.store("sha256:a:1", voice_id="va", name="na", provider="pa")
    cache1.store("sha256:b:2", voice_id="vb", name="nb", provider="pb")

    # Fresh instance
    cache2 = FingerprintCache(cache_file)
    hit_a = cache2.lookup("sha256:a:1")
    hit_b = cache2.lookup("sha256:b:2")

    assert hit_a is not None and hit_a.voice_id == "va"
    assert hit_b is not None and hit_b.voice_id == "vb"


# ---------------------------------------------------------------------------
# Idempotency — store(same fp) returns original
# ---------------------------------------------------------------------------


def test_store_same_fingerprint_returns_original_entry(tmp_path: Path):
    """Spec §5.2: same sample → same voice_id, even on repeated store."""
    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)

    first = cache.store(
        "sha256:same:1000",
        voice_id="v_first",
        name="alan",
        provider="fishaudio",
    )

    # Second call with a DIFFERENT voice_id and name but same fingerprint
    # must return the FIRST entry unchanged.
    second = cache.store(
        "sha256:same:1000",
        voice_id="v_second",
        name="alan-v2",
        provider="fishaudio",
    )

    assert second.voice_id == first.voice_id == "v_first"
    assert second.name == first.name == "alan"
    assert second.created_at == first.created_at


def test_store_same_fingerprint_same_name_is_noop(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)

    e1 = cache.store("sha256:a:1", voice_id="v1", name="x", provider="p")
    e2 = cache.store("sha256:a:1", voice_id="v1", name="x", provider="p")

    assert e1.voice_id == e2.voice_id
    assert e1.created_at == e2.created_at


def test_store_same_fingerprint_new_name_logs_warning(tmp_path: Path, caplog):
    """Spec §5.2 explicitly notes first-write-wins with warning log."""
    import logging

    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)
    cache.store("sha256:a:1", voice_id="v1", name="first", provider="p")

    with caplog.at_level(logging.WARNING):
        cache.store("sha256:a:1", voice_id="v_other", name="second", provider="p")

    assert any("already cached" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Corrupted cache file handling
# ---------------------------------------------------------------------------


def test_corrupted_json_is_moved_aside(tmp_path: Path, caplog):
    """If voice-cache.json is not valid JSON, it's renamed aside and
    the cache starts fresh without crashing."""
    import logging

    cache_file = tmp_path / "voice-cache.json"
    cache_file.write_text("{ not valid json }", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        cache = FingerprintCache(cache_file)
        hit = cache.lookup("sha256:anything:0")

    assert hit is None
    assert any("corrupted" in r.message for r in caplog.records)

    # A corrupted-* file should now exist alongside
    corrupted = [
        p for p in tmp_path.iterdir() if "corrupted" in p.name
    ]
    assert len(corrupted) == 1


def test_corrupted_json_then_new_store_works(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache_file.write_text("garbage", encoding="utf-8")

    cache = FingerprintCache(cache_file)
    entry = cache.store("sha256:new:1", voice_id="vx", name="x", provider="p")

    assert entry.voice_id == "vx"
    # Fresh cache file was written
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["sha256:new:1"]


def test_non_object_json_treated_as_corrupted(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache_file.write_text("[]", encoding="utf-8")  # JSON array, not object

    cache = FingerprintCache(cache_file)
    assert cache.lookup("sha256:anything:0") is None


# ---------------------------------------------------------------------------
# all_entries / clear
# ---------------------------------------------------------------------------


def test_all_entries_returns_every_stored(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)
    cache.store("sha256:a:1", voice_id="va", name="na", provider="p")
    cache.store("sha256:b:2", voice_id="vb", name="nb", provider="p")

    entries = cache.all_entries()
    assert len(entries) == 2
    voice_ids = {e.voice_id for e in entries}
    assert voice_ids == {"va", "vb"}


def test_clear_empties_cache(tmp_path: Path):
    cache_file = tmp_path / "voice-cache.json"
    cache = FingerprintCache(cache_file)
    cache.store("sha256:a:1", voice_id="va", name="na", provider="p")

    cache.clear()

    assert cache.lookup("sha256:a:1") is None
    assert cache.all_entries() == []
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data == {}


# ---------------------------------------------------------------------------
# CloneEntry roundtrip
# ---------------------------------------------------------------------------


def test_clone_entry_to_json_dict_excludes_fingerprint():
    """Fingerprint is the dict KEY in the file, not part of the value."""
    entry = CloneEntry(
        voice_id="v1",
        name="n1",
        provider="p1",
        created_at="2026-04-15T10:00:00Z",
        fingerprint="sha256:x:1",
    )
    d = entry.to_json_dict()
    assert "fingerprint" not in d
    assert d["voice_id"] == "v1"


def test_clone_entry_from_json_dict_roundtrip():
    entry = CloneEntry(
        voice_id="v1",
        name="n1",
        provider="p1",
        created_at="2026-04-15T10:00:00Z",
        fingerprint="sha256:x:1",
    )
    reconstructed = CloneEntry.from_json_dict("sha256:x:1", entry.to_json_dict())
    assert reconstructed == entry
