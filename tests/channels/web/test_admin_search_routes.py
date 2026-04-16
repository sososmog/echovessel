"""Worker θ · GET /api/admin/memory/search route tests.

Mirrors the pattern used by ``test_admin_memory_routes.py`` — file-backed
SQLite + TestClient against a Runtime built via ``config_override``.
Concept-node rows are seeded directly so the test does not depend on
the consolidate pipeline.
"""

from __future__ import annotations

import tempfile

from fastapi.testclient import TestClient
from sqlmodel import Session as DbSession

from echovessel.channels.web.app import build_web_app
from echovessel.channels.web.channel import WebChannel
from echovessel.channels.web.sse import SSEBroadcaster
from echovessel.core.types import NodeType
from echovessel.memory import ConceptNode
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
id = "search-test"
display_name = "SearchTest"

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


def _build_rig() -> tuple[Runtime, TestClient]:
    tmp = tempfile.mkdtemp(prefix="echovessel-search-")
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


def _seed(
    rt: Runtime,
    *,
    description: str,
    node_type: NodeType = NodeType.EVENT,
    emotion_tags: list[str] | None = None,
    relational_tags: list[str] | None = None,
) -> int:
    with DbSession(rt.ctx.engine) as db:
        row = ConceptNode(
            persona_id=rt.ctx.persona.id,
            user_id="self",
            type=node_type,
            description=description,
            emotion_tags=emotion_tags or [],
            relational_tags=relational_tags or [],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)


# ---------------------------------------------------------------------------
# Empty / smoke
# ---------------------------------------------------------------------------


def test_search_empty_database_returns_zero_hits() -> None:
    _rt, client = _build_rig()
    with client:
        resp = client.get("/api/admin/memory/search", params={"q": "rain"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["q"] == "rain"
    assert body["type"] == "all"
    assert body["total"] == 0
    assert body["items"] == []
    assert body["matched_snippets"] == []


def test_search_missing_q_returns_422() -> None:
    _rt, client = _build_rig()
    with client:
        resp = client.get("/api/admin/memory/search")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Hit / miss + snippet
# ---------------------------------------------------------------------------


def test_search_english_term_via_fts5_returns_snippet_with_highlights() -> None:
    rt, client = _build_rig()
    target_id = _seed(rt, description="it started raining heavily this evening")
    _seed(rt, description="sunshine on a quiet afternoon")
    with client:
        resp = client.get("/api/admin/memory/search", params={"q": "raining"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == target_id
    snip = body["matched_snippets"][0]
    assert snip["node_id"] == target_id
    assert "<b>" in snip["snippet"] and "</b>" in snip["snippet"]
    assert "raining" in snip["snippet"].lower()


def test_search_short_cjk_term_falls_back_to_like_with_snippet() -> None:
    """SQLite trigram tokenizer can't match terms shorter than 3 chars.
    The hybrid path falls back to ``LIKE`` for 2-char CJK queries and
    still produces a hand-rolled ``<b>``-wrapped snippet."""

    rt, client = _build_rig()
    target_id = _seed(rt, description="今天下雨了，心情低落")
    _seed(rt, description="阳光明媚的下午")
    with client:
        resp = client.get("/api/admin/memory/search", params={"q": "下雨"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == target_id
    snip = body["matched_snippets"][0]
    assert snip["node_id"] == target_id
    assert "<b>下雨</b>" in snip["snippet"]


def test_search_special_characters_are_safe() -> None:
    """FTS5 reserves AND OR NOT NEAR ( ) * : ^ " ? — the sanitiser must
    treat them as literals so this query simply finds zero matches
    (rather than 500-ing on syntax)."""

    rt, client = _build_rig()
    _seed(rt, description="quiet afternoon")
    with client:
        resp = client.get(
            "/api/admin/memory/search",
            params={"q": "() AND NEAR ?"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# Type and tag filters
# ---------------------------------------------------------------------------


def test_search_type_events_excludes_thoughts() -> None:
    rt, client = _build_rig()
    _seed(rt, description="rainy morning event", node_type=NodeType.EVENT)
    _seed(
        rt, description="rainy morning thought", node_type=NodeType.THOUGHT
    )
    with client:
        resp = client.get(
            "/api/admin/memory/search",
            params={"q": "rainy", "type": "events"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["node_type"] == "event"


def test_search_type_thoughts_excludes_events() -> None:
    rt, client = _build_rig()
    _seed(rt, description="rainy morning event", node_type=NodeType.EVENT)
    _seed(
        rt, description="rainy morning thought", node_type=NodeType.THOUGHT
    )
    with client:
        resp = client.get(
            "/api/admin/memory/search",
            params={"q": "rainy", "type": "thoughts"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["node_type"] == "thought"


def test_search_tag_filter_matches_emotion_tag() -> None:
    rt, client = _build_rig()
    target_id = _seed(
        rt,
        description="evening rain event",
        emotion_tags=["sadness"],
    )
    _seed(rt, description="evening rain event", emotion_tags=["calm"])
    with client:
        resp = client.get(
            "/api/admin/memory/search",
            params={"q": "rain", "tag": "sadness"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == target_id


def test_search_tag_filter_matches_relational_tag() -> None:
    rt, client = _build_rig()
    target_id = _seed(
        rt,
        description="dinner with mother",
        relational_tags=["family"],
    )
    _seed(rt, description="dinner with friend", relational_tags=["friend"])
    with client:
        resp = client.get(
            "/api/admin/memory/search",
            params={"q": "dinner", "tag": "family"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == target_id


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_search_pagination_offset_and_limit() -> None:
    rt, client = _build_rig()
    for i in range(7):
        _seed(rt, description=f"raining hard {i}")
    with client:
        first = client.get(
            "/api/admin/memory/search",
            params={"q": "raining", "limit": 3, "offset": 0},
        ).json()
        second = client.get(
            "/api/admin/memory/search",
            params={"q": "raining", "limit": 3, "offset": 3},
        ).json()
    assert first["total"] == 7
    assert second["total"] == 7
    assert len(first["items"]) == 3
    assert len(second["items"]) == 3
    first_ids = {it["id"] for it in first["items"]}
    second_ids = {it["id"] for it in second["items"]}
    # Two pages must not overlap.
    assert first_ids.isdisjoint(second_ids)


def test_search_invalid_type_returns_422() -> None:
    _rt, client = _build_rig()
    with client:
        resp = client.get(
            "/api/admin/memory/search",
            params={"q": "x", "type": "all-of-them"},
        )
    assert resp.status_code == 422
