"""Admin HTTP routes for the Web channel (Stage 3).

Implements the five admin endpoints locked in
``develop-docs/web-v1/03-stage-3-tracker.md`` §3:

- ``GET  /api/state``                        — daemon state + onboarding gate
- ``GET  /api/admin/persona``                — persona + full core-block snapshot
- ``POST /api/admin/persona/onboarding``     — one-shot first-time setup
- ``POST /api/admin/persona``                — partial update of persona fields
- ``POST /api/admin/persona/voice-toggle``   — flip persona.voice_enabled

The router is built by :func:`build_admin_router` which closes over a
live :class:`echovessel.runtime.app.Runtime`. Memory writes go through
:func:`echovessel.memory.append_to_core_block`; memory reads use a
fresh ``sqlmodel.Session`` bound to ``runtime.ctx.engine``.

Design constraints (see §3 of the tracker):

- The contract is literally locked. No new fields, no renames, no
  alternate shapes. Two concurrent workers are consuming it in
  parallel for a TS client and an end-to-end test; any drift breaks
  their work.
- Empty core blocks are returned as empty strings, not omitted keys.
- ``onboarding_required`` is driven solely by whether there is at
  least one ``core_blocks`` row for the configured ``persona_id``.
- The persona's ``display_name`` is mutated both on-disk
  (``config.toml``) and in-memory
  (``ctx.persona.display_name``) so a subsequent ``GET
  /api/admin/persona`` reflects the new value without a restart.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session as DbSession
from sqlmodel import func, select

from echovessel.core.types import BlockLabel, NodeType
from echovessel.memory import (
    CoreBlock,
    Persona,
    append_to_core_block,
)
from echovessel.memory.models import ConceptNode, RecallMessage

log = logging.getLogger(__name__)

# NOTE: ``runtime`` is typed as ``Any`` to avoid importing
# :class:`echovessel.runtime.app.Runtime` at module load time. That
# import would reverse the layered-architecture contract
# (``channels → memory|voice → core``) enforced by ``lint-imports``.
# The router closes over a live Runtime at call time and only reads
# the attributes documented below.


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class OnboardingRequest(BaseModel):
    """Body for ``POST /api/admin/persona/onboarding``.

    All fields are required (the frontend sends them even when empty),
    but empty strings are accepted and silently skipped at write time.
    """

    display_name: str = Field(..., min_length=1, max_length=256)
    persona_block: str = Field(...)
    self_block: str = Field(...)
    user_block: str = Field(...)
    mood_block: str = Field(...)


class PersonaUpdateRequest(BaseModel):
    """Body for ``POST /api/admin/persona``.

    Every field is optional — the server applies only the keys that
    are actually present in the request body.
    """

    display_name: str | None = Field(default=None, max_length=256)
    persona_block: str | None = None
    self_block: str | None = None
    user_block: str | None = None
    mood_block: str | None = None
    relationship_block: str | None = None


class VoiceToggleRequest(BaseModel):
    """Body for ``POST /api/admin/persona/voice-toggle``."""

    enabled: bool


# Map the JSON keys used on the wire to the memory BlockLabel values.
# ``onboarding`` has no relationship_block (§3 locked shape) so it is
# absent here; ``persona_update`` has the full set.
_ONBOARDING_LABELS: tuple[tuple[str, BlockLabel], ...] = (
    ("persona_block", BlockLabel.PERSONA),
    ("self_block", BlockLabel.SELF),
    ("user_block", BlockLabel.USER),
    ("mood_block", BlockLabel.MOOD),
)

_UPDATE_LABELS: tuple[tuple[str, BlockLabel], ...] = (
    ("persona_block", BlockLabel.PERSONA),
    ("self_block", BlockLabel.SELF),
    ("user_block", BlockLabel.USER),
    ("mood_block", BlockLabel.MOOD),
    ("relationship_block", BlockLabel.RELATIONSHIP),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_id_for_label(label: BlockLabel, user_id: str) -> str | None:
    """Return the per-row ``user_id`` for a given block label.

    Shared blocks (persona/self/mood) use NULL; per-user blocks
    (user/relationship) carry the actual user_id. Mirrors the business
    rule in :mod:`echovessel.memory.models.CoreBlock`.
    """

    if label in (BlockLabel.PERSONA, BlockLabel.SELF, BlockLabel.MOOD):
        return None
    return user_id


def _load_core_blocks_dict(
    db: DbSession, *, persona_id: str, user_id: str
) -> dict[str, str]:
    """Return every label → content mapping, defaulting missing labels to ''."""

    stmt = select(CoreBlock).where(
        CoreBlock.persona_id == persona_id,
        CoreBlock.deleted_at.is_(None),  # type: ignore[union-attr]
        (CoreBlock.user_id.is_(None)) | (CoreBlock.user_id == user_id),  # type: ignore[union-attr]
    )
    rows = list(db.exec(stmt))

    out: dict[str, str] = {
        BlockLabel.PERSONA.value: "",
        BlockLabel.SELF.value: "",
        BlockLabel.USER.value: "",
        BlockLabel.MOOD.value: "",
        BlockLabel.RELATIONSHIP.value: "",
    }
    for row in rows:
        label_value = getattr(row.label, "value", row.label)
        if label_value in out:
            out[label_value] = row.content or ""
    return out


def _count_rows(db: DbSession, model: type) -> int:
    return int(db.exec(select(func.count()).select_from(model)).one() or 0)


def _count_core_blocks_for_persona(db: DbSession, persona_id: str) -> int:
    stmt = (
        select(func.count())
        .select_from(CoreBlock)
        .where(
            CoreBlock.persona_id == persona_id,
            CoreBlock.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    )
    return int(db.exec(stmt).one() or 0)


def _write_blocks(
    db: DbSession,
    *,
    persona_id: str,
    user_id: str,
    pairs: list[tuple[BlockLabel, str]],
    source: str,
) -> None:
    """Write a batch of label/content pairs via ``append_to_core_block``.

    Empty content strings are skipped — the import API rejects empty
    writes and the spec allows callers to send empty blocks in
    onboarding / partial update payloads. The provenance payload is
    the minimum the import audit log expects.
    """

    for label, content in pairs:
        if not content or not content.strip():
            continue
        append_to_core_block(
            db,
            persona_id=persona_id,
            user_id=_user_id_for_label(label, user_id),
            label=label.value,
            content=content,
            provenance={"source": source},
        )


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def build_admin_router(*, runtime: Any) -> APIRouter:
    """Assemble the admin router bound to a live Runtime.

    The router is flat (no sub-router nesting) so each path is fully
    explicit in the decorator — matching §3 of the tracker verbatim
    is easier to verify this way than via nested prefix math.
    """

    router = APIRouter(tags=["admin"])
    # Default user_id — MVP daemon only ever talks to the single local
    # user and this matches every other runtime callsite.
    user_id = "self"

    def _persona_id() -> str:
        return runtime.ctx.persona.id

    def _open_db() -> DbSession:
        return DbSession(runtime.ctx.engine)

    # ---- GET /api/state -------------------------------------------------

    @router.get("/api/state")
    async def get_state() -> dict[str, Any]:
        persona_id = _persona_id()
        with _open_db() as db:
            core_block_count = _count_core_blocks_for_persona(db, persona_id)
            message_count = _count_rows(db, RecallMessage)
            event_count = int(
                db.exec(
                    select(func.count())
                    .select_from(ConceptNode)
                    .where(ConceptNode.type == NodeType.EVENT)
                ).one()
                or 0
            )
            thought_count = int(
                db.exec(
                    select(func.count())
                    .select_from(ConceptNode)
                    .where(ConceptNode.type == NodeType.THOUGHT)
                ).one()
                or 0
            )

        return {
            "persona": {
                "id": persona_id,
                "display_name": runtime.ctx.persona.display_name,
                "voice_enabled": bool(runtime.ctx.persona.voice_enabled),
                "has_voice_id": runtime.ctx.persona.voice_id is not None,
            },
            "onboarding_required": core_block_count == 0,
            "memory_counts": {
                "core_blocks": core_block_count,
                "messages": message_count,
                "events": event_count,
                "thoughts": thought_count,
            },
        }

    # ---- GET /api/admin/persona ----------------------------------------

    @router.get("/api/admin/persona")
    async def get_persona() -> dict[str, Any]:
        persona_id = _persona_id()
        with _open_db() as db:
            blocks = _load_core_blocks_dict(
                db, persona_id=persona_id, user_id=user_id
            )
        return {
            "id": persona_id,
            "display_name": runtime.ctx.persona.display_name,
            "voice_enabled": bool(runtime.ctx.persona.voice_enabled),
            "voice_id": runtime.ctx.persona.voice_id,
            "core_blocks": blocks,
        }

    # ---- POST /api/admin/persona/onboarding ----------------------------

    @router.post("/api/admin/persona/onboarding")
    async def post_onboarding(req: OnboardingRequest) -> dict[str, Any]:
        persona_id = _persona_id()

        with _open_db() as db:
            existing_count = _count_core_blocks_for_persona(db, persona_id)
            if existing_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "onboarding already completed; use POST "
                        "/api/admin/persona to update individual blocks"
                    ),
                )

            pairs = [
                (label, getattr(req, field))
                for field, label in _ONBOARDING_LABELS
            ]
            _write_blocks(
                db,
                persona_id=persona_id,
                user_id=user_id,
                pairs=pairs,
                source="admin_onboarding",
            )

            # Update Persona row's display_name so downstream DB readers
            # match the new name, then commit inside the same session.
            persona_row = db.get(Persona, persona_id)
            if persona_row is not None:
                persona_row.display_name = req.display_name
                db.add(persona_row)
                db.commit()

        # Mutate runtime in-memory copy and persist to config.toml so the
        # daemon survives a restart with the new display name.
        runtime.ctx.persona.display_name = req.display_name
        _try_persist_display_name(runtime, req.display_name)

        return {"ok": True, "persona_id": persona_id}

    # ---- POST /api/admin/persona ---------------------------------------

    @router.post("/api/admin/persona")
    async def post_persona(req: PersonaUpdateRequest) -> dict[str, Any]:
        persona_id = _persona_id()

        with _open_db() as db:
            pairs: list[tuple[BlockLabel, str]] = []
            for field, label in _UPDATE_LABELS:
                value = getattr(req, field, None)
                if value is None:
                    continue
                pairs.append((label, value))
            _write_blocks(
                db,
                persona_id=persona_id,
                user_id=user_id,
                pairs=pairs,
                source="admin_persona_update",
            )

            if req.display_name is not None:
                persona_row = db.get(Persona, persona_id)
                if persona_row is not None:
                    persona_row.display_name = req.display_name
                    db.add(persona_row)
                    db.commit()

        if req.display_name is not None:
            runtime.ctx.persona.display_name = req.display_name
            _try_persist_display_name(runtime, req.display_name)

        return {"ok": True}

    # ---- POST /api/admin/persona/voice-toggle --------------------------

    @router.post("/api/admin/persona/voice-toggle")
    async def post_voice_toggle(req: VoiceToggleRequest) -> dict[str, Any]:
        if runtime.ctx.config_path is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cannot toggle voice_enabled without a config file",
            )
        try:
            await runtime.update_persona_voice_enabled(bool(req.enabled))
        except RuntimeError as e:
            # Runtime raises RuntimeError for both config_override mode
            # and atomic-write failure. The config_override path is
            # already guarded above, so anything here is a disk error.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            ) from e
        return {
            "ok": True,
            "voice_enabled": bool(runtime.ctx.persona.voice_enabled),
        }

    return router


def _try_persist_display_name(runtime: Any, new_name: str) -> None:
    """Best-effort atomic write of ``[persona].display_name`` to config.toml.

    Matches the same rollback-safe pattern as
    :meth:`Runtime.update_persona_voice_enabled`: on failure, log a
    warning and leave the in-memory mutation in place. Admin write
    routes never refuse on a disk error — the user's edit is
    preserved for the current process lifetime.
    """

    if runtime.ctx.config_path is None:
        # `config_override` mode — nothing to persist. In-memory
        # mutation already happened in the caller; a future restart
        # with the same override will obviously revert it, but that's
        # fine because config_override is a tests-only path.
        return
    try:
        runtime._atomic_write_config_field(
            section="persona", field="display_name", value=new_name
        )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "failed to persist persona.display_name=%r to config.toml: %s",
            new_name,
            e,
        )


__all__ = ["build_admin_router"]
