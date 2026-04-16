"""Worker ι · Event ↔ Thought provenance trace route tests.

Exercises:

- GET /api/admin/memory/thoughts/{id}/trace
- GET /api/admin/memory/events/{id}/dependents

Each test seeds the filling graph directly via DbSession so the route
tests are decoupled from the consolidate / reflect pipeline.
"""

from __future__ import annotations

import tempfile
from datetime import date

from fastapi.testclient import TestClient
from sqlmodel import Session as DbSession

from echovessel.channels.web.app import build_web_app
from echovessel.channels.web.channel import WebChannel
from echovessel.channels.web.sse import SSEBroadcaster
from echovessel.core.types import MessageRole, NodeType
from echovessel.memory import (
    ConceptNode,
    ConceptNodeFilling,
    Persona,
    RecallMessage,
    User,
)
from echovessel.memory.models import Session as RecallSession
from echovessel.runtime import (
    Runtime,
    build_zero_embedder,
    load_config_from_str,
)
from echovessel.runtime.llm import StubProvider


def _toml(data_dir: str) -> str:
    return f"""
[runtime]
data_dir = "{data_dir}"
log_level = "warn"

[persona]
id = "p_trace"
display_name = "Trace"

[memory]
db_path = "memory.db"

[llm]
provider = "stub"
api_key_env = ""

[consolidate]
worker_poll_seconds = 1
worker_max_retries = 1

[idle_scanner]
interval_seconds = 60
"""


def _build() -> tuple[Runtime, TestClient]:
    tmp = tempfile.mkdtemp(prefix="echovessel-trace-")
    cfg = load_config_from_str(_toml(tmp))
    rt = Runtime.build(
        None,
        config_override=cfg,
        llm=StubProvider(fallback="ok"),
        embed_fn=build_zero_embedder(),
    )
    broadcaster = SSEBroadcaster()
    channel = WebChannel(debounce_ms=50)
    channel.attach_broadcaster(broadcaster)
    app = build_web_app(
        channel=channel,
        broadcaster=broadcaster,
        runtime=rt,
        heartbeat_seconds=0.5,
    )
    return rt, TestClient(app)


def _seed_lineage(rt: Runtime) -> dict:
    """Seed one thought backed by two events across two sessions, plus
    one orphaned filling link to make sure the routes filter it out."""
    with DbSession(rt.ctx.engine) as db:
        if db.get(Persona, "p_trace") is None:
            db.add(Persona(id="p_trace", display_name="Trace"))
        if db.get(User, "self") is None:
            db.add(User(id="self", display_name="Alan"))
        db.commit()

        sess_a = RecallSession(
            id="sess_a",
            persona_id="p_trace",
            user_id="self",
            channel_id="test",
        )
        sess_b = RecallSession(
            id="sess_b",
            persona_id="p_trace",
            user_id="self",
            channel_id="test",
        )
        db.add(sess_a)
        db.add(sess_b)
        db.commit()

        msg = RecallMessage(
            session_id="sess_a",
            persona_id="p_trace",
            user_id="self",
            channel_id="test",
            role=MessageRole.USER,
            content="source message",
            day=date.today(),
        )
        db.add(msg)
        db.commit()

        event_a = ConceptNode(
            persona_id="p_trace",
            user_id="self",
            type=NodeType.EVENT,
            description="Event from session A",
            emotional_impact=3,
            source_session_id="sess_a",
        )
        event_b = ConceptNode(
            persona_id="p_trace",
            user_id="self",
            type=NodeType.EVENT,
            description="Event from session B",
            emotional_impact=4,
            source_session_id="sess_b",
        )
        event_orphan = ConceptNode(
            persona_id="p_trace",
            user_id="self",
            type=NodeType.EVENT,
            description="Event whose filling link was orphaned",
            emotional_impact=2,
            source_session_id="sess_a",
        )
        isolated_event = ConceptNode(
            persona_id="p_trace",
            user_id="self",
            type=NodeType.EVENT,
            description="Event nobody reflected on",
            emotional_impact=1,
            source_session_id="sess_b",
        )
        db.add(event_a)
        db.add(event_b)
        db.add(event_orphan)
        db.add(isolated_event)
        db.commit()
        db.refresh(event_a)
        db.refresh(event_b)
        db.refresh(event_orphan)
        db.refresh(isolated_event)

        thought = ConceptNode(
            persona_id="p_trace",
            user_id="self",
            type=NodeType.THOUGHT,
            description="Alan tends to open up after calm stretches",
            emotional_impact=2,
        )
        isolated_thought = ConceptNode(
            persona_id="p_trace",
            user_id="self",
            type=NodeType.THOUGHT,
            description="A thought with no source events yet",
            emotional_impact=1,
        )
        db.add(thought)
        db.add(isolated_thought)
        db.commit()
        db.refresh(thought)
        db.refresh(isolated_thought)

        # Two live links + one orphaned link.
        db.add(ConceptNodeFilling(parent_id=thought.id, child_id=event_a.id))
        db.add(ConceptNodeFilling(parent_id=thought.id, child_id=event_b.id))
        db.add(
            ConceptNodeFilling(
                parent_id=thought.id,
                child_id=event_orphan.id,
                orphaned=True,
            )
        )
        db.commit()

        return {
            "thought_id": thought.id,
            "isolated_thought_id": isolated_thought.id,
            "event_a_id": event_a.id,
            "event_b_id": event_b.id,
            "event_orphan_id": event_orphan.id,
            "isolated_event_id": isolated_event.id,
        }


# ---------------------------------------------------------------------------
# GET /api/admin/memory/thoughts/{id}/trace
# ---------------------------------------------------------------------------


def test_thought_trace_returns_source_events_and_sessions() -> None:
    """A thought with two live filling rows surfaces both source events
    and the de-duplicated set of source sessions. The orphaned link is
    filtered out."""
    rt, client = _build()
    ids = _seed_lineage(rt)

    with client:
        resp = client.get(
            f"/api/admin/memory/thoughts/{ids['thought_id']}/trace"
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["thought_id"] == ids["thought_id"]

    ev_ids = {ev["id"] for ev in body["source_events"]}
    assert ev_ids == {ids["event_a_id"], ids["event_b_id"]}
    # Orphaned filling must not leak through.
    assert ids["event_orphan_id"] not in ev_ids

    # Every returned event carries the 4 trace fields we commit to.
    for ev in body["source_events"]:
        assert set(ev.keys()) == {
            "id",
            "description",
            "created_at",
            "source_session_id",
        }
        assert ev["description"]

    assert set(body["source_sessions"]) == {"sess_a", "sess_b"}


def test_thought_trace_empty_when_no_live_filling() -> None:
    """A thought with zero filling rows returns empty arrays, not 404."""
    rt, client = _build()
    ids = _seed_lineage(rt)

    with client:
        resp = client.get(
            f"/api/admin/memory/thoughts/{ids['isolated_thought_id']}/trace"
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_events"] == []
    assert body["source_sessions"] == []


def test_thought_trace_404_when_id_is_event() -> None:
    """The route guards against cross-type misuse — passing an event id
    to /thoughts/{id}/trace must 404."""
    rt, client = _build()
    ids = _seed_lineage(rt)
    with client:
        resp = client.get(
            f"/api/admin/memory/thoughts/{ids['event_a_id']}/trace"
        )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# GET /api/admin/memory/events/{id}/dependents
# ---------------------------------------------------------------------------


def test_event_dependents_returns_thoughts() -> None:
    rt, client = _build()
    ids = _seed_lineage(rt)

    with client:
        resp = client.get(
            f"/api/admin/memory/events/{ids['event_a_id']}/dependents"
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event_id"] == ids["event_a_id"]
    thought_ids = {t["id"] for t in body["dependent_thoughts"]}
    assert thought_ids == {ids["thought_id"]}


def test_event_dependents_empty_when_no_thought_cites_it() -> None:
    rt, client = _build()
    ids = _seed_lineage(rt)
    with client:
        resp = client.get(
            f"/api/admin/memory/events/{ids['isolated_event_id']}/dependents"
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["dependent_thoughts"] == []


def test_event_dependents_404_when_id_is_thought() -> None:
    rt, client = _build()
    ids = _seed_lineage(rt)
    with client:
        resp = client.get(
            f"/api/admin/memory/events/{ids['thought_id']}/dependents"
        )
    assert resp.status_code == 404, resp.text
