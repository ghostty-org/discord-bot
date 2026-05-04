# pyright: reportPrivateUsage=false

from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from githubkit.versions.latest.models import SimpleUser

from tests.webhooks.utils import make_pr

from app.components.github_integration.webhooks.prs import (
    _format_reviewer,
    _reduce_diff_hunk,
    pr_footer,
)

if TYPE_CHECKING:
    from app.bot import EmojiName


@pytest.mark.parametrize(
    ("state", "draft", "merged", "expected"),
    [
        ("open", False, False, "pull_open"),
        ("open", True, False, "pull_draft"),
        ("closed", False, True, "pull_merged"),
        ("closed", False, False, "pull_closed"),
    ],
)
def test_pr_footer(state: str, draft: bool, merged: bool, expected: EmojiName) -> None:
    pr = make_pr(number=42, title="Test PR", state=state, draft=draft, merged=merged)
    assert pr_footer(pr) == (expected, "PR #42: Test PR")


@pytest.mark.parametrize(
    ("hunk", "expected"),
    [
        (
            "@@ -1,3 +1,3 @@\n context line\n-old line\n+new line\n another context",
            "-old line\n+new line",
        ),
        ("@@ -1,3 +1,3 @@\n context line\nanother context\nmore context", ""),
        (
            "@@ -1,3 +1,3 @@\n context\n+new line 1\n+new line 2",
            "+new line 1\n+new line 2",
        ),
        (
            "@@ -1,3 +1,3 @@\n context\n-old line 1\n-old line 2",
            "-old line 1\n-old line 2",
        ),
    ],
)
def test_reduce_diff_hunk(hunk: str, expected: str) -> None:
    assert _reduce_diff_hunk(hunk) == expected


def test_format_reviewer_team() -> None:
    team = Mock(())
    team.name = "core-team"
    event = Mock((), requested_team=team)
    assert _format_reviewer(event) == "the `core-team` team"


def test_format_reviewer_user() -> None:
    user = Mock(
        SimpleUser,
        model_dump=Mock(
            (),
            return_value={
                "login": "reviewer",
                "html_url": "https://github.com/reviewer",
                "avatar_url": "https://avatars.githubusercontent.com/u/1",
            },
        ),
    )
    event = Mock((), requested_reviewer=user)
    result = _format_reviewer(event)
    assert "reviewer" in result


def test_format_reviewer_none() -> None:
    assert _format_reviewer(Mock(())) == "`?`"
