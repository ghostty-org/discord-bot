from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from typing import TYPE_CHECKING, cast

from githubkit.exception import RequestFailed
from githubkit.versions.latest.models import PullRequestReviewComment, ReactionRollup
from zig_codeblocks import extract_codeblocks

from app.components.github_integration.comments.discussions import (
    get_discussion_comment,
)
from app.components.github_integration.mentions.cache import entity_cache
from app.components.github_integration.models import (
    Comment,
    EntityGist,
    GitHubUser,
    Reactions,
)
from app.setup import gh
from app.utils import TTRCache

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import AsyncIterator

    from githubkit.typing import Missing
    from pydantic import BaseModel

COMMENT_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s]+)/"
    r"(issues|discussions|pull)/(\d+)/?#(\w+?-?)(\d+)"
)
FALLBACK_AUTHOR = GitHubUser(
    login="GitHub",
    url="https://github.com",
    icon_url="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png",
)
STATE_TO_COLOR = {
    "APPROVED": 0x2ECC71,  # green
    "CHANGES_REQUESTED": 0xE74C3C,  # red
}
EVENT_COLOR = 0x3498DB  # blue
ENTITY_UPDATE_EVENTS = frozenset({"closed", "locked", "merged", "reopened", "unlocked"})
SUPPORTED_EVENTS = {
    "assigned": "Assigned `{event.assignee.login}`",
    "labeled": "Added the `{event.label.name}` label",
    "milestoned": "Added this to the `{event.milestone.title}` milestone",
    "review_requested": "Requested review from `{reviewer}`",
    "unassigned": "Unassigned `{event.assignee.login}`",
    "unlabeled": "Removed the `{event.label.name}` label",
}


class CommentCache(TTRCache[tuple[EntityGist, str, int], Comment]):
    async def fetch(self, key: tuple[EntityGist, str, int]) -> None:
        entity_gist, event_type, event_no = key
        coro = {
            "discussioncomment-": get_discussion_comment,
            "issuecomment-": _get_issue_comment,
            "pullrequestreview-": _get_pr_review,
            "discussion_r": _get_pr_review_comment,
            "event-": _get_event,
            "discussion-": _get_entity_starter,
            "issue-": _get_entity_starter,
        }.get(event_type)
        if coro is None:
            return
        with suppress(RequestFailed):
            self[key] = await coro(entity_gist, event_no)


comment_cache = CommentCache(minutes=30)


def _make_author(user: BaseModel | None) -> GitHubUser:
    return GitHubUser(**user.model_dump()) if user else FALLBACK_AUTHOR


def _make_reactions(rollup: ReactionRollup | Missing[ReactionRollup]) -> Reactions:
    """Asserts that `rollup` is not Missing."""
    if not isinstance(rollup, ReactionRollup):
        # While every usage of this function takes Reactions | None, this
        # function shouldn't even be called if the API doesn't return reactions
        # for some case, so a TypeError is thrown instead of returning None to
        # catch any bugs instead of silently removing the reactions.
        msg = f"expected type ReactionRollup, found {type(rollup)}"
        raise TypeError(msg)
    return Reactions(**rollup.model_dump())


async def _get_issue_comment(entity_gist: EntityGist, comment_id: int) -> Comment:
    owner, repo, _ = entity_gist
    comment_resp, entity = await asyncio.gather(
        gh.rest.issues.async_get_comment(owner, repo, comment_id),
        entity_cache.get(entity_gist),
    )
    comment = comment_resp.parsed_data
    return Comment(
        author=_make_author(comment.user),
        body=cast("str", comment.body),
        reactions=_make_reactions(comment.reactions),
        entity=entity,
        entity_gist=entity_gist,
        created_at=comment.created_at,
        html_url=comment.html_url,
    )


async def _get_pr_review(entity_gist: EntityGist, comment_id: int) -> Comment:
    comment = (
        await gh.rest.pulls.async_get_review(*entity_gist, comment_id)
    ).parsed_data
    return Comment(
        author=_make_author(comment.user),
        body=comment.body,
        # For some reason, GitHub's API doesn't include them for PR reviews,
        # despite there being reactions visible in the UI.
        reactions=None,
        entity=await entity_cache.get(entity_gist),
        entity_gist=entity_gist,
        created_at=cast("dt.datetime", comment.submitted_at),
        html_url=comment.html_url,
        color=STATE_TO_COLOR.get(comment.state),
        kind="Review",
    )


async def _get_pr_review_comment(entity_gist: EntityGist, comment_id: int) -> Comment:
    owner, repo, _ = entity_gist
    comment = (
        await gh.rest.pulls.async_get_review_comment(owner, repo, comment_id)
    ).parsed_data
    return Comment(
        author=_make_author(comment.user),
        body=_prettify_suggestions(comment),
        reactions=_make_reactions(comment.reactions),
        entity=await entity_cache.get(entity_gist),
        entity_gist=entity_gist,
        created_at=comment.created_at,
        html_url=comment.html_url,
        kind="Review comment",
    )


def _prettify_suggestions(comment: PullRequestReviewComment) -> str:
    suggestions = [
        c for c in extract_codeblocks(comment.body) if c.lang == "suggestion"
    ]
    body = comment.body
    if not suggestions:
        return body

    start = cast("int | None", comment.original_start_line)
    end = cast("int", comment.original_line)
    hunk_size = end - (end if start is None else start) + 1
    hunk_as_deleted_diff = "\n".join(
        ("-" + line[1:] if line[0] == "+" else line)
        for line in comment.diff_hunk.splitlines()[-hunk_size:]
    )

    for sug in suggestions:
        suggestion_as_added_diff = f"{hunk_as_deleted_diff}\n" + "\n".join(
            f"+{line}" for line in sug.body.splitlines()
        )
        body = body.replace(
            _make_crlf_codeblock("suggestion", sug.body.replace("\r\n", "\n")),
            _make_crlf_codeblock("diff", suggestion_as_added_diff),
            1,
        )
    return body


def _make_crlf_codeblock(lang: str, body: str) -> str:
    # GitHub seems to use CRLF for everything...
    return f"```{lang}\n{body}\n```".replace("\n", "\r\n")


async def _get_event(entity_gist: EntityGist, comment_id: int) -> Comment:
    owner, repo, entity_no = entity_gist
    event = (await gh.rest.issues.async_get_event(owner, repo, comment_id)).parsed_data
    if event.event not in SUPPORTED_EVENTS.keys() | ENTITY_UPDATE_EVENTS:
        body = f"👻 Unsupported event: `{event.event}`"
    elif event.event == "review_requested":
        # Special-cased to handle requests for both users and teams
        if event.requested_reviewer:
            reviewer = event.requested_reviewer.login
        else:
            assert event.requested_team
            # Throwing in the org name to make it clear that it's a team
            org_name = event.requested_team.html_url.split("/", 5)[4]
            reviewer = f"{org_name}/{event.requested_team.name}"
        body = SUPPORTED_EVENTS[event.event].format(reviewer=reviewer)
    elif event.event in ENTITY_UPDATE_EVENTS:
        entity = await entity_cache.get(entity_gist)
        body = f"{event.event.capitalize()} the {entity.kind}"
        if event.lock_reason:
            body += f"\nReason: `{event.lock_reason or 'unspecified'}`"
    else:
        body = SUPPORTED_EVENTS[event.event].format(event=event)
    # The API doesn't return an html_url, gotta construct it manually.
    # It's fine to say "issues" here, GitHub will resolve the correct type
    url = f"https://github.com/{owner}/{repo}/issues/{entity_no}#event-{comment_id}"
    return Comment(
        author=_make_author(event.actor),
        body=f"**{body}**",
        entity=await entity_cache.get(entity_gist),
        entity_gist=entity_gist,
        created_at=event.created_at,
        html_url=url,
        kind="Event",
        color=EVENT_COLOR,
    )


async def _get_entity_starter(entity_gist: EntityGist, _: int) -> Comment:
    entity = await entity_cache.get(entity_gist)
    return Comment(
        author=entity.user,
        body=entity.body or "",
        reactions=entity.reactions,
        entity=entity,
        entity_gist=entity_gist,
        created_at=entity.created_at,
        html_url=entity.html_url,
    )


async def get_comments(content: str) -> AsyncIterator[Comment]:
    found_comments = set[Comment]()
    for match in COMMENT_PATTERN.finditer(content):
        owner, repo, _, number, event, event_no = map(str, match.groups())
        entity_gist = EntityGist(owner, repo, int(number))
        with suppress(KeyError):
            comment = await comment_cache.get((entity_gist, event, int(event_no)))
            if comment not in found_comments:
                found_comments.add(comment)
                yield comment
