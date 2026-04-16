"""Shared fixtures for `tests/import_/` — in-memory DB + seeded persona."""

from __future__ import annotations

import pytest
from sqlmodel import Session as DbSession

from echovessel.memory import (
    Persona,
    User,
    create_all_tables,
    create_engine,
)
from echovessel.memory.backends.sqlite import SQLiteBackend


@pytest.fixture()
def engine():
    eng = create_engine(":memory:")
    create_all_tables(eng)
    with DbSession(eng) as db:
        db.add(Persona(id="p_test", display_name="TestPersona"))
        db.add(User(id="self", display_name="Alan"))
        db.commit()
    return eng


@pytest.fixture()
def db_session_factory(engine):
    def _factory():
        return DbSession(engine)

    return _factory


@pytest.fixture()
def backend(engine):
    return SQLiteBackend(engine)
