import asyncio
import re
from contextlib import suppress
from typing import TYPE_CHECKING, cast, final, override

from githubkit.exception import RequestFailed
from githubkit.versions.latest.models import IssuePropPullRequest, ReactionRollup
from zig_codeblocks import extract_codeblocks

from .discussions import get_discussion_comment
from app.components.github_integration.entities.cache import entity_cache
from app.components.github_integration.models import (
    Comment,
    EntityGist,
    GitHubUser,
    Reactions,
)
from app.config import gh
from toolbox.cache import TTRCache
from toolbox.discord import escape_special

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

# Many of the events below are from GitHub's official documentation, which can be found
# at https://docs.github.com/en/rest/using-the-rest-api/issue-event-types. However, some
# of the events there aren't included:
#  - commented, committed, cross-referenced, reviewed — these seem to be unavailable
#    from the REST API for issue events, and the bot completely ignores them
#    (_get_event() isn't even called) if it's not available there because fetching them
#    throws a 404.
#  - deployment_environment_changed — this theoretically could be supported, but it has
#    not yet been determined how to create this: if you see this in the wild or are able
#    to create such an event, please open an issue with a link to the event in question!
#  - mentioned, subscribed, unsubscribed, user_blocked — these don't make sense, as they
#    don't resemble anything you could find on the timeline (which is the precondition
#    for obtaining a link to it without somehow using the API). unsubscribed also isn't
#    available from the REST API for issue events.
# Furthermore, many events below are not documented, and have been obtained from running
# assorted links obtained from the timeline UI through the API. Thus, this list of
# supported events is not complete: it is simply ones the maintainers remembered seeing
# or noticed while doing something completely unrelated. A URL to example events is
# provided above each event, to facilitate future modifications without needing to hunt
# through assorted GitHub repositories to find suitable event links. If you ever find
# a link for which Ghostty Bot responds with "Unsupported event", please open an issue!
# Finally, many events below do not have as much information as is available in GitHub's
# UI, because for some reason GitHub's API rarely includes most important information:
# the only things that is consistently present is the event name, actor, timestamp, and
# issue/PR. All events below are supported only to the extent possible; quantity is
# valued over quality since it's rarely possible to provide any more than a general
# description.
ENTITY_UPDATE_EVENTS = frozenset({
    # https://github.com/ghostty-org/ghostty/issues/9395#event-20597662923
    # https://github.com/ghostty-org/ghostty/issues/9724#event-21209589708
    # https://github.com/ghostty-org/ghostty/pull/9849#event-21431934056
    # https://github.com/ghostty-org/discord-bot/pull/180#event-16964640728
    "closed",
    # https://github.com/ghostty-org/ghostty/issues/3558#event-15774573241
    # https://github.com/ghostty-org/ghostty/pull/8289#event-19270334048
    # https://github.com/ghostty-org/ghostty/issues/189#event-16236928844
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21541841009
    "locked",
    # https://github.com/ghostty-org/ghostty/pull/9882#event-21530110251
    "merged",
    # https://github.com/ghostty-org/ghostty/issues/5934#event-16526189159
    # https://github.com/ghostty-org/discord-bot/pull/189#event-16964696368
    "reopened",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21541842543
    "unlocked",
    # https://github.com/ghostty-org/ghostty/issues/3558#event-15774572749
    "pinned",
    # https://github.com/ghostty-org/ghostty/issues/189#event-21294606586
    # https://github.com/NixOS/nixpkgs/issues/223562#event-9412768466
    "unpinned",
    # https://github.com/astral-sh/ty/issues/246#event-17558740145
    # https://github.com/uBlockOrigin/uBOL-home/issues/351#event-17703330347
    "transferred",
})
# NOTE: some events are special-cased in _get_event() itself.
SUPPORTED_EVENTS: dict[str, str | Callable[[IssueEvent], str]] = {
    # https://github.com/ghostty-org/ghostty/pull/8479#event-19434379557
    # https://github.com/ghostty-org/ghostty/pull/8365#event-19305035157
    # https://github.com/ghostty-org/discord-bot/issues/155#event-16525531765
    # https://github.com/ghostty-org/discord-bot/issues/378#event-20007243169
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540911478
    "assigned": "Assigned `{event.assignee.login}`",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540912045
    "unassigned": "Unassigned `{event.assignee.login}`",
    # https://github.com/ghostty-org/ghostty/pull/8365#event-19305034038
    # https://github.com/ghostty-org/discord-bot/issues/113#event-15807270712
    # https://github.com/ghostty-org/discord-bot/issues/118#event-15815381050
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540915909
    "labeled": "Added the `{event.label.name}` label",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540916899
    "unlabeled": "Removed the `{event.label.name}` label",
    # https://github.com/ghostty-org/ghostty/issues/7128#event-17324195909
    # https://github.com/ghostty-org/discord-bot/issues/236#event-17747044482
    "issue_type_added": "Added an issue type",
    #  https://github.com/ghostty-org/discord-bot/issues/236#event-17747063469
    "issue_type_changed": "Changed the issue type",
    # https://github.com/ghostty-org/discord-bot/issues/236#event-17747091355
    "issue_type_removed": "Removed the issue type",
    # https://github.com/ghostty-org/ghostty/pull/9756#event-21257176103
    # https://github.com/ghostty-org/ghostty/pull/9758#event-21488581260
    # https://github.com/ghostty-org/ghostty/pull/9832#event-21428833545
    "milestoned": "Added this to the `{event.milestone.title}` milestone",
    # https://github.com/ghostty-org/ghostty/issues/5491#event-16302256854
    "demilestoned": "Removed this from the `{event.milestone.title}` milestone",
    # https://github.com/gleam-lang/awesome-gleam/issues/160#event-14908148573
    "converted_from_draft": "Converted this from a draft issue",
    # https://github.com/ghostty-org/discord-bot/pull/175#event-16555527337
    # https://github.com/ghostty-org/discord-bot/pull/431#event-21540933434
    "convert_to_draft": "Marked this pull request as draft",
    # https://github.com/ghostty-org/discord-bot/pull/175#event-16529671127
    # https://github.com/ghostty-org/discord-bot/pull/176#event-16596899731
    "ready_for_review": "Marked this pull request as ready for review",
    # https://github.com/ghostty-org/discord-bot/pull/234#event-17752890907
    # https://github.com/ghostty-org/ghostty/pull/9890#event-21539711044
    "review_requested": "Requested a review from `{reviewer}`",
    # https://github.com/ghostty-org/discord-bot/pull/234#event-17752986102
    # https://github.com/ghostty-org/discord-bot/pull/234#event-17753052966
    "review_request_removed": "Removed the request for a review from `{reviewer}`",
    # https://github.com/trag1c/monalisten/pull/15#event-21534908956
    "copilot_work_started": "Started a Copilot review",
    # https://github.com/ghostty-org/ghostty/pull/5341#event-16053815030
    "auto_merge_enabled": "Enabled auto-merge",
    # https://github.com/microsoft/terminal/pull/18903#event-17640118811
    "auto_squash_enabled": "Enabled auto-merge (squash)",
    # https://github.com/ghostty-org/ghostty/pull/5341#event-16053815030
    # https://github.com/microsoft/terminal/pull/18901#event-17626618807
    "auto_merge_disabled": "Disabled auto-merge",
    # https://github.com/ghostty-org/ghostty/pull/5341#event-16053900676
    "head_ref_deleted": "Deleted the head branch",
    # https://github.com/Pix-xiP/remake/pull/2#event-13989779969
    "head_ref_restored": "Restored the head branch",
    # https://github.com/ghostty-org/ghostty/pull/5650#event-16271684386
    # https://github.com/ghostty-org/discord-bot/pull/175#event-16529067881
    "head_ref_force_pushed": lambda event: (
        "Force-pushed the head branch to "
        + _format_commit_id(event, cast("str", event.commit_id))
    ),
    # https://github.com/ghostty-org/discord-bot/pull/151#event-16323374495
    "base_ref_changed": "Changed the base branch",
    # https://github.com/ghostty-org/discord-bot/pull/154#event-16440303050
    "automatic_base_change_succeeded": "Base automatically changed",
    # (A link has not yet been procured: it's included only because it's documented.)
    "automatic_base_change_failed": "Automatic base change failed",
    # https://github.com/ghostty-org/ghostty/issues/601#event-14492268323
    # https://github.com/ghostty-org/ghostty/issues/2915#event-15601932131
    "converted_to_discussion": "Converted this issue to a discussion",
    # https://github.com/ghostty-org/ghostty/issues/6709#event-16762188684
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540953657
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540955887
    "parent_issue_added": "Added a parent issue",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540954322
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540956147
    "parent_issue_removed": "Removed a parent issue",
    # https://github.com/ghostty-org/ghostty/issues/5255#event-16762188659
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540955881
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540953649
    "sub_issue_added": "Added a sub-issue",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540956142
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540954319
    "sub_issue_removed": "Removed a sub-issue",
    # https://github.com/ghostty-org/ghostty/issues/3074#event-15773680889
    # https://github.com/ghostty-org/ghostty/issues/5191#event-15981365503
    # https://github.com/microsoft/terminal/issues/3061#event-16688362043
    "marked_as_duplicate": "Marked an issue as a duplicate of this one",
    # https://github.com/microsoft/terminal/issues/3061#event-16688383563
    "unmarked_as_duplicate": "Unmarked an issue as a duplicate of this one",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540951762
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540961662
    "blocking_added": "Marked this issue as blocking another",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540952702
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540961913
    "blocking_removed": "Unmarked this issue as blocking another",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540961666
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540951768
    "blocked_by_added": "Marked this issue as blocked by another",
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21540961919
    # https://github.com/ghostty-org/discord-bot/issues/236#event-21540952710
    "blocked_by_removed": "Unmarked this issue as blocked by another",
    # https://github.com/python/mypy/issues/6700#event-16524881873
    "referenced": lambda event: (
        "Referenced this issue in commit "
        + _format_commit_id(event, cast("str", event.commit_id), preserve_repo_url=True)
    ),
    # https://github.com/ghostty-org/ghostty/issues/5491#event-16304505401
    "renamed": lambda event: (
        f"Changed the title ~~{
            escape_special((rename := cast('IssueEventRename', event.rename)).from_)
        }~~ {escape_special(rename.to)}"
    ),
    # https://github.com/microsoft/terminal/pull/17421#event-13349470395
    "added_to_merge_queue": "Added this pull request to the merge queue",
    # https://github.com/google-gemini/gemini-cli/pull/4625#event-19668902591
    "removed_from_merge_queue": "Removed this pull request from the merge queue",
    # https://github.com/Foxboron/sbctl/pull/300#event-12587455392
    "deployed": lambda event: (
        "Deployed this" + f" via {escape_special(event.performed_via_github_app.name)}"
        if event.performed_via_github_app is not None
        else ""
    ),
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21541845202
    # https://github.com/ghostty-org/discord-bot/pull/429#event-21541845197
    "connected": lambda event: (
        "Linked an issue that may be closed by this pull request"
        if isinstance(cast("Issue", event.issue).pull_request, IssuePropPullRequest)
        else "Linked a pull request that may close this issue"
    ),
    # https://github.com/ghostty-org/discord-bot/issues/430#event-21541847026
    # https://github.com/ghostty-org/discord-bot/pull/429#event-21541847022
    "disconnected": lambda event: (
        "Removed a link to "
        + (
            "a pull request"
            if isinstance(cast("Issue", event.issue).pull_request, IssuePropPullRequest)
            else "an issue"
        )
    ),
    # https://github.com/microsoft/terminal/pull/18903#event-17640120322
    # https://github.com/microsoft/terminal/pull/18901#event-17626622591
    "added_to_project_v2": "Added this to a project",
    # https://github.com/microsoft/terminal/pull/18903#event-17640120474
    # https://github.com/microsoft/terminal/pull/18903#event-17643846664
    # https://github.com/microsoft/terminal/pull/18901#event-17626622936
    # https://github.com/microsoft/terminal/pull/18901#event-17626622996
    # https://github.com/microsoft/terminal/pull/18901#event-17639416901
    # https://github.com/microsoft/terminal/pull/18901#event-17639425386
    "project_v2_item_status_changed": "Changed the status of this in a project",
    # https://github.com/microsoft/sudo/issues/2#event-13350207312
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
    # Special-cased to handle requests for both users and teams. There are example links
    # for these two in the dictionary near the top of the file.
    if event.event in ("review_requested", "review_request_removed"):
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
        body = f"{event.event.capitalize()} this {entity.kind.lower()}"
        if event.lock_reason:
            body += f"\nReason: `{event.lock_reason}`"
    # Special-cased since async functions need to be called. As per the comment near the
    # top of the file, here's a few examples of the review_dismissed event:
    #   - https://github.com/ghostty-org/ghostty/issues/4226#event-16286258029
    #   - https://github.com/ghrebote/test/pull/13#event-17587469081
    elif event.event == "review_dismissed":
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
