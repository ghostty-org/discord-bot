from unittest.mock import Mock

import pytest

from tests.webhooks.utils import make_pr, make_user

from app.components.github_integration.webhooks.vouch import (
    extract_vouch_details,
    find_vouch_command,
    is_vouch_pr,
)


@pytest.mark.parametrize(
    ("body", "command"),
    [
        ("!vouch @user", "vouch"),
        ("!unvouch @user", "unvouch"),
        ("!denounce @user", "denounce"),
        ("!vouch @user thanks for contributing!", "vouch"),
        ("!denounce @user AI slop", "denounce"),
        ("!thanks @user", None),
        ("vouch @user", None),
        ("", None),
        ("!", None),
        ("! vouch @user", None),
        ("This person is cool!\n\n!vouch @user", None),
    ],
)
def test_find_vouch_command(body: str, command: str | None) -> None:
    assert find_vouch_command(body) == command


@pytest.mark.parametrize(
    ("pr_title", "sender_login", "sender_type", "expected_result"),
    [
        ("Update VOUCHED list", "ghostty-vouch[bot]", "Bot", True),
        ("Fix bug", "ghostty-vouch[bot]", "Bot", False),
        ("Update VOUCHED list", "human", "User", False),
        ("Add feature", "developer", "User", False),
        ("Some bot PR", "some-other-bot[bot]", "Bot", False),
        ("As a large language model, I cannot open PRs", "Copilot", "Bot", False),
        ("Update VOUCHED list", "Copilot", "Bot", False),
    ],
)
def test_is_vouch_pr(
    pr_title: str, sender_login: str, sender_type: str, expected_result: bool
) -> None:
    event = Mock(
        ("pull_request", "sender"),
        pull_request=make_pr(title=pr_title),
        sender=make_user(login=sender_login, user_type=sender_type),
    )
    assert is_vouch_pr(event) is expected_result


@pytest.mark.parametrize(
    ("body", "entity_id", "comment_id", "vouchee"),
    [
        (
            "Triggered by [comment](https://github.com/ghostty-org/ghostty/"
            "issues/9999#issuecomment-3210987654) from @barfoo.\n\nVouch: @foobar",
            9999,
            3210987654,
            "foobar",
        ),
        (
            "Triggered by [comment](https://github.com/ghostty-org/ghostty/"
            "pull/123#issuecomment-9876543210) from @reviewer.\n\nVouch: @contributor",
            123,
            9876543210,
            "contributor",
        ),
        (
            "Triggered by [comment](https://github.com/ghostty-org/ghostty/"
            "discussions/456#discussioncomment-12345) from @user.\n\nVouch: @vouchee",
            456,
            12345,
            "vouchee",
        ),
    ],
)
def test_extract_vouch_details_valid(
    body: str, entity_id: int, comment_id: int, vouchee: str
) -> None:
    result = extract_vouch_details(body)
    assert result is not None
    _, eid, cid, v = result
    assert eid == entity_id
    assert cid == comment_id
    assert v == vouchee


@pytest.mark.parametrize("body", [None, "Vouch: @foobar", "", "No URL here"])
def test_extract_vouch_details_invalid(body: str | None) -> None:
    assert extract_vouch_details(body) is None
