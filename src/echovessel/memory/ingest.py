"""INGEST pipeline — write a message to L2 and track session state.

Responsibilities (per architecture v0.3 §3.1):
  1. Write message to recall_messages (L2)
  2. Count tokens via tiktoken
  3. Update session counters (message_count, total_tokens, last_message_at)
  4. Return the RecallMessage + the Session it lives in

Explicitly NOT:
  - Compute embeddings (L2 has no vector in MVP, see architecture §4.6)
  - Call LLM (extraction/reflection happen in consolidate pipeline)
  - Score emotional_impact (that happens in extraction at session close)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

from sqlmodel import Session as DbSession

from echovessel.core.types import MessageRole
from echovessel.memory.models import RecallMessage, Session
from echovessel.memory.observers import MemoryEventObserver
from echovessel.memory.sessions import (
    check_length_trigger,
    drain_and_fire_pending_lifecycle_events,
    get_or_create_open_session,
)
from echovessel.memory.tokens import estimate_tokens

log = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestResult:
    """Return value of `ingest_message` — useful for callers that need to
    react to session lifecycle events (e.g. enqueue extraction)."""

    message: RecallMessage
    session: Session
    session_closed: bool  # True if this message caused a max_length trigger


def ingest_message(
    db: DbSession,
    persona_id: str,
    user_id: str,
    channel_id: str,
    role: MessageRole,
    content: str,
    now: datetime | None = None,
    *,
    turn_id: str | None = None,
    observer: MemoryEventObserver | None = None,
) -> IngestResult:
    """Write a single message to L2, updating session state.

    `channel_id` identifies which channel the message arrived on (e.g. 'web',
    'discord:guild123', 'imessage'). It's used to pick/create the right
    session (sessions are per-channel) and is stored redundantly on the
    message row for fast per-channel history queries. Memory retrieval
    NEVER filters by channel_id — see DISCUSSION.md 2026-04-14 D4.

    v0.3 additions:
      - `turn_id`: optional debounce-layer turn identifier (see channels
        spec v0.2 §2.3a + memory schema v0.3). Persona replies to a user
        turn use the same turn_id as the user messages they answer.
        Legacy callers that don't know about turns pass None.
      - `observer`: optional post-commit hook. `on_message_ingested` is
        invoked after a successful commit with the persisted RecallMessage.
        Observer exceptions are caught and logged — they never roll back
        the memory write.

    Commits the transaction. Returns the persisted RecallMessage and the
    Session it lives in.
    """
    now = now or datetime.now()

    session = get_or_create_open_session(
        db, persona_id, user_id, channel_id, now=now
    )

    token_count = estimate_tokens(content)

    msg = RecallMessage(
        session_id=session.id,
        persona_id=persona_id,
        user_id=user_id,
        channel_id=channel_id,
        role=role,
        content=content,
        token_count=token_count,
        day=date.fromordinal(now.toordinal()),
        turn_id=turn_id,
        created_at=now,
    )
    db.add(msg)

    # Update session aggregates
    session.message_count += 1
    session.total_tokens += token_count
    session.last_message_at = now

    # If we just crossed max_length, mark closing. The caller can then
    # call `get_or_create_open_session` again for the next message.
    closed = check_length_trigger(db, session, now=now)

    db.commit()
    db.refresh(msg)
    db.refresh(session)

    # Round 4: drain session-lifecycle hooks that the session code
    # queued during `get_or_create_open_session` / any length-trigger
    # marking. This fires `on_new_session_started` for any fresh Session
    # row this call produced. Strictly post-commit per tracker §4 #7.
    drain_and_fire_pending_lifecycle_events()

    # Post-commit observer notification. Failure here MUST NOT roll back
    # the write (review M2/M3). Caller semantics: the message IS persisted
    # even if the observer raises.
    if observer is not None:
        try:
            observer.on_message_ingested(msg)
        except Exception as e:  # noqa: BLE001 — observer contract
            log.warning(
                "observer.on_message_ingested raised (msg id=%s): %s",
                msg.id,
                e,
            )

    return IngestResult(message=msg, session=session, session_closed=closed)
