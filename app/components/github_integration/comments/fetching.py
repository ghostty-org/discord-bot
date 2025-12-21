from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from typing import TYPE_CHECKING, cast, final, override

from githubkit.exception import RequestFailed
from githubkit.versions.latest.models import IssuePropPullRequest, ReactionRollup
from zig_codeblocks import extract_codeblocks

from .discussions import get_discussion_comment
from app.common.cache import TTRCache
from app.components.github_integration.entities.cache import entity_cache
from app.components.github_integration.models import (
    Comment,
    EntityGist,
    GitHubUser,
    Reactions,
)
from app.config import gh
from app.utils import escape_special

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import AsyncGenerator, Callable

    from githubkit.typing import Missing
    from githubkit.versions.latest.models import (
        Issue,
        IssueEvent,
        IssueEventDismissedReview,
        IssueEventRename,
        PullRequestReviewComment,
    )
    from pydantic import BaseModel

COMMENT_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\._]+)/"
    r"(issues|discussions|pull)/(\d+)/?#(\w+?-?)(\d+)"
)
STATE_TO_COLOR = {
    "APPROVED": 0x2ECC71,  # green
    "CHANGES_REQUESTED": 0xE74C3C,  # red
}
EVENT_COLOR = 0x3498DB  # blue
ENTITY_UPDATE_EVENTS = frozenset({
    "closed",
    "locked",
    "merged",
    "reopened",
    "unlocked",
    "pinned",
    "unpinned",
    "transferred",
})
SUPPORTED_EVENTS: dict[str, str | Callable[[IssueEvent], str]] = {
    "assigned": "Assigned `{event.assignee.login}`",
    "unassigned": "Unassigned `{event.assignee.login}`",
    "labeled": "Added the `{event.label.name}` label",
    "unlabeled": "Removed the `{event.label.name}` label",
    "issue_type_added": "Added an issue type",
    "issue_type_changed": "Changed the issue type",
    "issue_type_removed": "Removed the issue type",
    "milestoned": "Added this to the `{event.milestone.title}` milestone",
    "demilestoned": "Removed this from the `{event.milestone.title}` milestone",
    "converted_from_draft": "Converted this from a draft issue",
    "convert_to_draft": "Marked this pull request as draft",
    "ready_for_review": "Marked this pull request as ready for review",
    "review_requested": "Requested a review from `{reviewer}`",
    "review_request_removed": "Removed the request for a review from `{reviewer}`",
    "copilot_work_started": "Started a Copilot review",
    "auto_merge_enabled": "Enabled auto-merge",
    "auto_squash_enabled": "Enabled auto-merge (squash)",
    "auto_merge_disabled": "Disabled auto-merge",
    "head_ref_deleted": "Deleted the head branch",
    "head_ref_restored": "Restored the head branch",
    "head_ref_force_pushed": lambda event: (
        "Force-pushed the head branch to "
        + _format_commit_id(event, cast("str", event.commit_id))
    ),
    "base_ref_changed": "Changed the base branch",
    "automatic_base_change_failed": "Automatic base change failed",
    "automatic_base_change_succeeded": "Base automatically changed",
    "converted_to_discussion": "Converted this issue to a discussion",
    "parent_issue_added": "Added a parent issue",
    "parent_issue_removed": "Removed a parent issue",
    "sub_issue_added": "Added a sub-issue",
    "sub_issue_removed": "Removed a sub-issue",
    "marked_as_duplicate": "Marked an issue as a duplicate of this one",
    "unmarked_as_duplicate": "Unmarked an issue as a duplicate of this one",
    "blocking_added": "Marked this issue as blocking another",
    "blocking_removed": "Unmarked this issue as blocking another",
    "blocked_by_added": "Marked this issue as blocked by another",
    "blocked_by_removed": "Unmarked this issue as blocked by another",
    "referenced": lambda event: (
        "Referenced this issue in commit "
        + _format_commit_id(event, cast("str", event.commit_id), preserve_repo_url=True)
    ),
    "renamed": lambda event: (
        f"Changed the title ~~{
            escape_special((rename := cast('IssueEventRename', event.rename)).from_)
        }~~ {escape_special(rename.to)}"
    ),
    "added_to_merge_queue": "Added this pull request to the merge queue",
    "removed_from_merge_queue": "Removed this pull request from the merge queue",
    "deployed": lambda event: (
        "Deployed this" + f" via {escape_special(event.performed_via_github_app.name)}"
        if event.performed_via_github_app is not None
        else ""
    ),
    "connected": lambda event: (
        "Linked an issue that may be closed by this pull request"
        if isinstance(cast("Issue", event.issue).pull_request, IssuePropPullRequest)
        else "Linked a pull request that may close this issue"
    ),
    "disconnected": lambda event: (
        "Removed a link to " + "a pull request"
        if isinstance(cast("Issue", event.issue).pull_request, IssuePropPullRequest)
        else "an issue"
    ),
    "added_to_project_v2": "Added this to a project",
    "project_v2_item_status_changed": "Changed the status of this in a project",
    "comment_deleted": "Deleted a comment",
}


def _format_commit_id(
    event: IssueEvent,
    commit_id: str,
    *,
    preserve_repo_url: bool = False,
    shorten_to: int = 7,
) -> str:
    # HACK: there does not seem to be any other way to get the HTML URL of the
    # repository. And for some reason the HTML URL requires `commit` while the API URL
    # requires `commits` (note the `s`)...
    if event.commit_url is None:
        # We tried.
        preserve_repo_url = False
    url = (
        (
            cast("str", event.commit_url)
            if preserve_repo_url
            else cast("Issue", event.issue).repository_url
        )
        .replace("api.", "", count=1)
        .replace("/repos", "", count=1)
        .replace("commits", "commit")
    )
    if not preserve_repo_url:
        url += f"/commit/{commit_id}"
    return f"[`{commit_id[:shorten_to]}`](<{url}>)"


@final
class CommentCache(TTRCache[tuple[EntityGist, str, int], Comment]):
    @override
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
            if result := await coro(entity_gist, event_no):
                self[key] = result


comment_cache = CommentCache(minutes=30)


def _make_author(user: BaseModel | None) -> GitHubUser:
    return GitHubUser(**user.model_dump()) if user else GitHubUser.default()


def _make_reactions(rollup: ReactionRollup | Missing[ReactionRollup]) -> Reactions:
    """Asserts that `rollup` is not Missing."""
    if not isinstance(rollup, ReactionRollup):
        # While every usage of this function takes Reactions | None, this function
        # shouldn't even be called if the API doesn't return reactions for some case, so
        # a TypeError is thrown instead of returning None to catch any bugs instead of
        # silently removing the reactions.
        msg = f"expected type ReactionRollup, found {type(rollup)}"
        raise TypeError(msg)
    return Reactions(**rollup.model_dump())


async def _get_issue_comment(
    entity_gist: EntityGist, comment_id: int
) -> Comment | None:
    owner, repo, _ = entity_gist
    comment_resp, entity = await asyncio.gather(
        gh.rest.issues.async_get_comment(owner, repo, comment_id),
        entity_cache.get(entity_gist),
    )
    comment = comment_resp.parsed_data
    return entity and Comment(
        author=_make_author(comment.user),
        body=cast("str", comment.body),
        reactions=_make_reactions(comment.reactions),
        entity=entity,
        entity_gist=entity_gist,
        created_at=comment.created_at,
        html_url=comment.html_url,
    )


async def _get_pr_review(entity_gist: EntityGist, comment_id: int) -> Comment | None:
    comment = (
        await gh.rest.pulls.async_get_review(*entity_gist, comment_id)
    ).parsed_data
    entity = await entity_cache.get(entity_gist)
    return entity and Comment(
        author=_make_author(comment.user),
        body=comment.body,
        # For some reason, GitHub's API doesn't include them for PR reviews, despite
        # there being reactions visible in the UI.
        reactions=None,
        entity=entity,
        entity_gist=entity_gist,
        created_at=cast("dt.datetime", comment.submitted_at),
        html_url=comment.html_url,
        color=STATE_TO_COLOR.get(comment.state),
        kind="Review",
    )


async def _get_pr_review_comment(
    entity_gist: EntityGist, comment_id: int
) -> Comment | None:
    owner, repo, _ = entity_gist
    comment = (
        await gh.rest.pulls.async_get_review_comment(owner, repo, comment_id)
    ).parsed_data
    entity = await entity_cache.get(entity_gist)
    return entity and Comment(
        author=_make_author(comment.user),
        body=_prettify_suggestions(comment),
        reactions=_make_reactions(comment.reactions),
        entity=entity,
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


async def _get_event(entity_gist: EntityGist, comment_id: int) -> Comment | None:
    owner, repo, entity_no = entity_gist
    event = (await gh.rest.issues.async_get_event(owner, repo, comment_id)).parsed_data
    entity = await entity_cache.get(entity_gist)
    if not entity:
        return None
    if event.event in ("review_requested", "review_request_removed"):
        # Special-cased to handle requests for both users and teams
        if event.requested_reviewer:
            reviewer = event.requested_reviewer.login
        else:
            assert event.requested_team
            # Throwing in the org name to make it clear that it's a team
            org_name = event.requested_team.html_url.split("/", 5)[4]
            reviewer = f"{org_name}/{event.requested_team.name}"
        formatter = SUPPORTED_EVENTS[event.event]
        if not isinstance(formatter, str):
            msg = f"formatter for {event.event} must be a string"
            raise TypeError(msg)
        body = formatter.format(reviewer=reviewer)
    elif event.event in ENTITY_UPDATE_EVENTS:
        body = f"{event.event.capitalize()} the {entity.kind.lower()}"
        if event.lock_reason:
            body += f"\nReason: `{event.lock_reason}`"
    elif event.event == "review_dismissed":
        # Special-cased since async functions need to be called
        dismissed_review = cast("IssueEventDismissedReview", event.dismissed_review)
        review = (
            await gh.rest.pulls.async_get_review(
                owner, repo, entity_no, dismissed_review.review_id
            )
        ).parsed_data
        commit_id = dismissed_review.dismissal_commit_id
        author = f"`{review.user.login}`'s" if review.user is not None else "a"
        commit = (
            f" via {_format_commit_id(event, commit_id)}"
            if isinstance(commit_id, str)
            else ""
        )
        msg = f": {m}" if (m := dismissed_review.dismissal_message) is not None else ""
        body = f"Dismissed {author} [stale review](<{review.html_url}>){commit}{msg}"
    elif formatter := SUPPORTED_EVENTS.get(event.event):
        body = (
            formatter(event) if callable(formatter) else formatter.format(event=event)
        )
    else:
        body = f"👻 Unsupported event: `{event.event}`"
    # The API doesn't return an html_url, gotta construct it manually. It's fine to say
    # "issues" here, GitHub will resolve the correct type
    url = f"https://github.com/{owner}/{repo}/issues/{entity_no}#event-{comment_id}"
    return Comment(
        author=_make_author(event.actor),
        body=f"**{body}**",
        entity=entity,
        entity_gist=entity_gist,
        created_at=event.created_at,
        html_url=url,
        kind="Event",
        color=EVENT_COLOR,
    )


async def _get_entity_starter(entity_gist: EntityGist, _: int) -> Comment | None:
    entity = await entity_cache.get(entity_gist)
    return entity and Comment(
        author=entity.user,
        body=entity.body or "",
        reactions=entity.reactions,
        entity=entity,
        entity_gist=entity_gist,
        created_at=entity.created_at,
        html_url=entity.html_url,
    )


async def get_comments(content: str) -> AsyncGenerator[Comment]:
    found_comments = set[Comment]()
    for match in COMMENT_PATTERN.finditer(content):
        owner, repo, _, number, event, event_no = map(str, match.groups())
        entity_gist = EntityGist(owner, repo, int(number))
        comment = await comment_cache.get((entity_gist, event, int(event_no)))
        if comment and comment not in found_comments:
            found_comments.add(comment)
            yield comment
