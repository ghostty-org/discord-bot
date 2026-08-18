from unittest.mock import AsyncMock, Mock, patch

import discord as dc
import pytest

from app.bot import GhosttyBot
from app.components.github_integration import repositories
from app.components.github_integration.code_links import CodeLinks, ContentCache
from app.components.github_integration.comments.fetching import (
    COMMENT_PATTERN,
    comment_cache,
    get_comments,
)
from app.components.github_integration.commit_links import (
    COMMIT_SHA_PATTERN,
    CommitLinks,
)
from app.components.github_integration.entities.resolution import (
    resolve_entity_signatures,
)
from app.config import Config, config_var


def make_message(content: str) -> dc.Message:
    return Mock(dc.Message, content=content, author=Mock((), id=1))


def mock_repo_access(*, privileged: bool) -> None:
    member = Mock(dc.Member)
    guild = Mock(dc.Guild, get_member=Mock((), return_value=member))
    config_var.set(
        Mock(
            Config,
            ghostty_guild=guild,
            is_privileged_github=Mock((), return_value=privileged),
        )
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content",
    ["meta#12", "https://github.com/ghostty-org/meta/issues/12", "ghostty-org/meta#12"],
)
@pytest.mark.parametrize(
    ("privileged", "expected"),
    [(True, [("ghostty-org", "meta", 12)]), (False, [])],
)
async def test_meta_entity_mentions_require_privilege(
    content: str,
    *,
    privileged: bool,
    expected: list[tuple[tuple[str, str, int], None]],
) -> None:
    mock_repo_access(privileged=privileged)

    # sig[0] to strip the kind hint which would otherwise complicate the parametrization
    assert [
        sig[0] async for sig in resolve_entity_signatures(make_message(content))
    ] == expected


def test_public_repos_do_not_require_privilege() -> None:
    config = Mock((), side_effect=AssertionError("public repo checked permissions"))
    config_var.set(config)

    assert repositories.can_link_repo(Mock(dc.Member, id=1), "ghostty-org", "ghostty")
    config.assert_not_called()


@pytest.mark.anyio
async def test_private_code_links_are_filtered_before_fetching() -> None:
    mock_repo_access(privileged=False)

    code_links = CodeLinks(Mock(GhosttyBot))
    code_links.cache = Mock(ContentCache, get=AsyncMock(return_value="secret"))
    code_message = make_message(
        "https://github.com/ghostty-org/meta/blob/main/private.py#L1"
    )
    assert [snippet async for snippet in code_links.get_snippets(code_message)] == []
    code_links.cache.get.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("anchor", ["issuecomment-123", "event-456"])
async def test_private_event_links_are_filtered_before_fetching(anchor: str) -> None:
    mock_repo_access(privileged=False)

    comment_get = AsyncMock()
    with patch.object(comment_cache, "get", comment_get):
        comment_message = make_message(
            f"https://github.com/ghostty-org/meta/issues/12#{anchor}"
        )
        assert COMMENT_PATTERN.search(comment_message.content)
        assert [comment async for comment in get_comments(comment_message)] == []
        comment_get.assert_not_awaited()


@pytest.mark.anyio
async def test_private_commit_links_are_filtered_before_fetching() -> None:
    mock_repo_access(privileged=False)

    message = make_message("https://github.com/ghostty-org/meta/commit/abcdef0")
    matches = COMMIT_SHA_PATTERN.findall(message.content)
    assert matches
    assert [
        commit
        async for commit in CommitLinks.resolve_repo_signatures(message.author, matches)
    ] == []
