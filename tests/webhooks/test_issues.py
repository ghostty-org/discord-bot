from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from app.components.github_integration.webhooks.issues import (
    IssueLike,
    get_issue_emoji,
    remove_discussion_div,
)

if TYPE_CHECKING:
    from app.bot import EmojiName


@pytest.mark.parametrize(
    ("state", "reason", "expected"),
    [
        ("open", None, "issue_open"),
        ("closed", "completed", "issue_closed_completed"),
        ("closed", "not_planned", "issue_closed_unplanned"),
        ("closed", "duplicate", "issue_closed_unplanned"),
    ],
)
def test_issue_emoji(state: str, reason: str | None, expected: EmojiName) -> None:
    issue = Mock(IssueLike, state=state, state_reason=reason)
    assert get_issue_emoji(issue) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "<div type='discussions-op-text'>\nActual content\n</div>",
            "\nActual content",
        ),
        ("Start<div type='discussions-op-text'>Middle</div>End", "StartMiddleEnd"),
        (None, None),
        ("No div tag here", "No div tag here"),
    ],
)
def test_remove_discussion_div(body: str | None, expected: str | None) -> None:
    assert remove_discussion_div(body) == expected
