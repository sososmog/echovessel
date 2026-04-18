"""Session-wide test safety nets.

Autouse fixtures here run before every test in the suite. Keep them
tightly scoped: they should only exist to prevent tests from touching
the developer's host machine in ways the test can't control.
"""

from __future__ import annotations

import webbrowser

import pytest


@pytest.fixture(autouse=True)
def _no_real_browser_popup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real browser tabs from opening during tests.

    Runtime schedules :func:`webbrowser.open` on first-launch (fresh
    install detection). Smoke / startup tests that call ``rt.start()``
    on an empty DB trigger that path incidentally, which — without this
    fixture — pops a real browser window for every test run.

    ``monkeypatch`` at function scope re-applies per test, and
    ``test_first_launch.py`` monkeypatches ``webbrowser.open`` again
    inside its own test bodies: the second call wins, so those tests
    still see a fake they can observe.
    """

    monkeypatch.setattr(
        webbrowser, "open", lambda *args, **kwargs: False, raising=True
    )
