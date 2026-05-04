from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from app.components.github_integration.webhooks.discussions import (
    DiscussionLike,
    get_discussion_emoji,
)

if TYPE_CHECKING:
    from app.bot import EmojiName


@pytest.mark.parametrize(
    ("state", "reason", "answer", "expected"),
    [
        ("open", None, None, "discussion"),
        (
            "open",
            None,
            "https://example.com#discussioncomment-1",
            "discussion_answered",
        ),
        (
            "closed",
            "resolved",
            "https://example.com#discussioncomment-1",
            "discussion_answered",
        ),
        ("closed", "outdated", None, "discussion_outdated"),
        ("closed", "duplicate", None, "discussion_duplicate"),
    ],
)
def test_discussion_emoji(
    state: str, reason: str | None, answer: str | None, expected: EmojiName
) -> None:
    disc = Mock(
        DiscussionLike, state=state, state_reason=reason, answer_html_url=answer
    )
    assert get_discussion_emoji(disc) == expected
