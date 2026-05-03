from unittest.mock import Mock

import discord as dc
import pytest

from toolbox.messages import is_attachment_only


@pytest.mark.parametrize(
    ("attachments", "content", "preprocessed_content", "embeds", "result"),
    [
        ([], "", None, [], False),
        ([1], "", None, [], True),
        ([1, 2, 3], "", None, [], True),
        ([1, 2, 3], "foo", "", [], True),  # the pre-processing removes the content.
        ([1, 2, 3], "", "foo", [], False),
        ([], "", "foo", [], False),
        ([1, 2, 3], "", "", [1, 2], False),
        ([1, 2, 3], "", "foo", [1, 2], False),
        ([1, 2, 3], "foo", "bar", [], False),
        ([1, 2, 3], "foo", "bar", [1, 2], False),
    ],
)
def test_is_attachment_only(
    attachments: list[int],
    content: str,
    preprocessed_content: str | None,
    embeds: list[int],
    result: bool,
) -> None:
    # NOTE: we don't actually care about having real Discord objects here, we only care
    # about whether they are truthy, so ints are used everywhere.
    fake_message = Mock(
        dc.Message,
        attachments=attachments,
        components=[],
        content=content,
        preprocessed_content=preprocessed_content,
        embeds=embeds,
        poll=None,
        stickers=[],
    )
    assert (
        is_attachment_only(fake_message, preprocessed_content=preprocessed_content)
        == result
    )
