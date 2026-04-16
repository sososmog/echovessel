"""Re-export of memory observer types for import-path compatibility.

Runtime spec §17a.5 specifies
`from echovessel.memory.events import MemoryEventObserver` as the
canonical import path. M-round3 put the Protocol in
`echovessel.memory.observers`. This module bridges the two so both
paths resolve to the **same** class object and `register_observer`
behaves identically regardless of which import path the caller uses.

No new types are defined here — doing so would create two parallel
Protocols that silently disagree. Any lifecycle or per-write hook
changes go in `memory.observers`; this module just re-exports.

See `docs/memory/07-round4-tracker.md` §2.2 for the rationale and the
`test_events_module_reexport.py` guard test that enforces `id()`
identity between the two import paths.
"""

from __future__ import annotations

from echovessel.memory.observers import (
    MemoryEventObserver,
    NullObserver,
    register_observer,
    unregister_observer,
)

__all__ = [
    "MemoryEventObserver",
    "NullObserver",
    "register_observer",
    "unregister_observer",
]
