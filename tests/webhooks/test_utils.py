from unittest.mock import Mock, patch

import discord as dc
import pytest

from app.components.github_integration.webhooks.utils import EmbedContent, Footer


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
