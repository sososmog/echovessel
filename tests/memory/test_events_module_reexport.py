"""`memory.events` re-export contract.

Runtime spec §17a.5 says `from echovessel.memory.events import
MemoryEventObserver`. M-round3 placed the Protocol in `memory.observers`.
`memory.events` bridges the two so both import paths resolve to the
**same** class object (verified via `id()`). If anyone ever duplicates
the Protocol into `events.py`, this test fails loudly.
"""

from __future__ import annotations


def test_protocol_is_same_object_from_both_paths():
    from echovessel.memory.events import MemoryEventObserver as FromEvents
    from echovessel.memory.observers import MemoryEventObserver as FromObservers

    assert FromEvents is FromObservers
    assert id(FromEvents) == id(FromObservers)


def test_null_observer_is_same_object_from_both_paths():
    from echovessel.memory.events import NullObserver as FromEvents
    from echovessel.memory.observers import NullObserver as FromObservers

    assert FromEvents is FromObservers


def test_register_observer_is_same_function_from_both_paths():
    from echovessel.memory.events import register_observer as reg_events
    from echovessel.memory.observers import register_observer as reg_observers

    assert reg_events is reg_observers


def test_unregister_observer_is_same_function_from_both_paths():
    from echovessel.memory.events import unregister_observer as unreg_events
    from echovessel.memory.observers import (
        unregister_observer as unreg_observers,
    )

    assert unreg_events is unreg_observers


def test_events_module_exports_exact_symbol_set():
    from echovessel.memory import events

    assert set(events.__all__) == {
        "MemoryEventObserver",
        "NullObserver",
        "register_observer",
        "unregister_observer",
    }


def test_events_path_works_end_to_end():
    """Register via `memory.events.register_observer`, trigger an event,
    verify the hook fires — all symbols interoperate regardless of
    import path."""
    from sqlmodel import Session as DbSession

    from echovessel.core.types import MessageRole
    from echovessel.memory import (
        Persona,
        User,
        create_all_tables,
        create_engine,
    )
    from echovessel.memory.events import (
        register_observer,
        unregister_observer,
    )
    from echovessel.memory.ingest import ingest_message

    class _Spy:
        def __init__(self) -> None:
            self.fired = 0

        def on_new_session_started(self, session_id, persona_id, user_id):
            self.fired += 1

    spy = _Spy()
    register_observer(spy)
    try:
        engine = create_engine(":memory:")
        create_all_tables(engine)
        with DbSession(engine) as db:
            db.add(Persona(id="p_re", display_name="Re"))
            db.add(User(id="self", display_name="Alan"))
            db.commit()
            ingest_message(
                db, "p_re", "self", "web", MessageRole.USER, "hello"
            )
        assert spy.fired == 1
    finally:
        unregister_observer(spy)
