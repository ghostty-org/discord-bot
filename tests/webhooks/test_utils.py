# pyright: reportPrivateUsage=false
from functools import partial
from unittest.mock import Mock, patch

import discord as dc
import pytest
from githubkit_schemas.latest.models import (  # pyright: ignore[reportMissingTypeStubs]
    RepositoryWebhooks,
)

from app.components.github_integration.webhooks.utils import (
    GITHUB_DISCUSSION_URL,
    EmbedContent,
    Footer,
    _shorten_same_repo_links,
)


@pytest.mark.parametrize(
    ("param_name", "expected_length"), [("body", 500), ("description", 4096)]
)
def test_embed_content_dict_with_body(param_name: str, expected_length: int) -> None:
    content = EmbedContent(
        title="Test Title",
        url="https://example.com",
        **{param_name: "test content" * 350},
    )
    result = content.dict
    assert result["title"] == "Test Title"
    assert result["url"] == "https://example.com"

    assert "description" in result
    desc = result["description"]
    assert desc is not None
    assert "test content" in desc
    assert len(desc) == expected_length


def test_embed_content_dict_no_body_or_description() -> None:
    content = EmbedContent(title="Test Title", url="https://example.com")
    assert "description" not in content.dict


def test_footer_dict() -> None:
    with patch(
        "app.components.github_integration.webhooks.utils.emojis"
    ) as mock_emojis:
        mock_emojis.return_value = {
            "issue_open": Mock(dc.Emoji, url="https://example.com/emoji.png")
        }

        footer = Footer("issue_open", "Issue #1: Test")
        result = footer.dict

        assert result["text"] == "Issue #1: Test"
        assert result["icon_url"] == "https://example.com/emoji.png"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "https://github.com/ghostty-org/ghostty/discussions/8268#discussioncomment-14492426",
            "[#8268](https://github.com/ghostty-org/ghostty/discussions/8268#discussioncomment-14492426)",
        ),
        (
            "two months ago (https://github.com/ghostty-org/ghostty/pull/8912#issuecomm"
            "ent-4002278186), and there",
            "two months ago ([#8912](https://github.com/ghostty-org/ghostty/pull/8912#i"
            "ssuecomment-4002278186)), and there",
        ),
        (
            "see [#8912](https://github.com/ghostty-org/ghostty/pull/8912)",
            "see [#8912](https://github.com/ghostty-org/ghostty/pull/8912)",
        ),
        (
            "check out https://github.com/other-org/other-repo/pull/123",
            "check out https://github.com/other-org/other-repo/pull/123",
        ),
        (
            "(https://github.com/ghostty-org/ghostty/issues/999) for context",
            "([#999](https://github.com/ghostty-org/ghostty/issues/999)) for context",
        ),
    ],
)
def test_shorten_same_repo_links(source: str, expected: str) -> None:
    origin_repo = Mock(RepositoryWebhooks, full_name="ghostty-org/ghostty")
    shorten = partial(_shorten_same_repo_links, origin_repo)
    assert GITHUB_DISCUSSION_URL.sub(shorten, source) == expected
