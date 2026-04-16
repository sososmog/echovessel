"""Non-whitelist content_types raise ValueError (tracker §4 #2)."""

from __future__ import annotations

import pytest

from echovessel.import_.models import ContentItem
from echovessel.import_.routing import dispatch_item


def test_content_item_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown content_type"):
        ContentItem(
            content_type="mood_block",
            payload={"persona_id": "p", "user_id": "u"},
        )


def test_dispatch_item_rejects_raw_dict_with_bad_type(db_session_factory):
    # Bypass ContentItem's __post_init__ by constructing with a valid
    # type and then mutating via __dict__ (frozen dataclass workaround).
    item = ContentItem(
        content_type="persona_traits",
        payload={"persona_id": "p_test", "user_id": "self", "content": "x"},
    )
    object.__setattr__(item, "content_type", "fake_type")
    with pytest.raises(ValueError, match="unknown content_type"), db_session_factory() as db:
        dispatch_item(item, db=db, source="hash")
