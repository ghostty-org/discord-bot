import re
from typing import TYPE_CHECKING, Any, Protocol, cast

from loguru import logger

from app.components.github_integration.webhooks.utils import (
    EmbedContent,
    Footer,
    send_edit_difference,
    send_embed,
)
from app.components.github_integration.webhooks.vouch import (
    find_vouch_command,
    register_vouch_command,
)

if TYPE_CHECKING:
    from githubkit.typing import Missing
    from monalisten import Monalisten, events

    from app.bot import EmojiName, GhosttyBot
    from app.components.github_integration.webhooks.vouch import VouchQueue

DISCUSSION_DIV_TAG = re.compile(
    r"\s*<div type='discussions-op-text'>((?:.|\s)*?)\s*</div>\s*", re.MULTILINE
)


def remove_discussion_div(body: str | None) -> str | None:
    return body and DISCUSSION_DIV_TAG.sub(r"\g<1>", body)


class IssueLike(Protocol):
    title: str
    number: int
    html_url: str
    state: Any
    state_reason: Missing[str | None]


def get_issue_emoji(issue: IssueLike) -> EmojiName:
    if issue.state == "open":
        return "issue_open"
    if issue.state_reason == "completed":
        return "issue_closed_completed"
    return "issue_closed_unplanned"


def issue_footer(issue: IssueLike, /, *, emoji: EmojiName | None = None) -> Footer:
    return Footer(
        emoji or get_issue_emoji(issue), f"Issue #{issue.number}: {issue.title}"
    )


def issue_embed_content(
    issue: IssueLike,
    template: str,
    body: str | None = None,
    /,
    *,
    description: str | None = None,
) -> EmbedContent:
    return EmbedContent(
        template.format(f"issue #{issue.number}"), issue.html_url, body, description
    )


def register_hooks(
    bot: GhosttyBot, webhook: Monalisten, vouch_queue: VouchQueue
) -> None:
    @webhook.event.issues.opened
    async def _(event: events.IssuesOpened) -> None:
        issue = event.issue
        body = remove_discussion_div(issue.body)
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, "opened {}", body),
            issue_footer(issue, emoji="issue_open"),
            color="green",
            origin_repo=event.repository,
        )

    @webhook.event.issues.closed
    async def _(event: events.IssuesClosed) -> None:
        issue = event.issue
        match issue.state_reason:
            case "completed":
                color, emoji_kind = "purple", "completed"
            case "not_planned" | "duplicate":
                color, emoji_kind = "gray", "unplanned"
            case _:
                logger.warning("unexpected state reason: {}", issue.state_reason)
                return

        state_reason = cast("str", issue.state_reason).replace("_", " ")
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, f"closed {{}} as {state_reason}"),
            issue_footer(issue, emoji="issue_closed_" + emoji_kind),
            color=color,
        )

    @webhook.event.issues.reopened
    async def _(event: events.IssuesReopened) -> None:
        issue = event.issue
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, "reopened {}"),
            issue_footer(issue, emoji="issue_open"),
            color="green",
        )

    @webhook.event.issues.edited
    async def _(event: events.IssuesEdited) -> None:
        await send_edit_difference(bot, event, issue_embed_content, issue_footer)

    @webhook.event.issues.locked
    async def _(event: events.IssuesLocked) -> None:
        issue = event.issue
        reason = f" as {r}" if (r := issue.active_lock_reason) else ""
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, f"locked {{}}{reason}"),
            issue_footer(issue),
            color="orange",
        )

    @webhook.event.issues.unlocked
    async def _(event: events.IssuesUnlocked) -> None:
        issue = event.issue
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, "unlocked {}"),
            issue_footer(issue),
            color="blue",
        )

    @webhook.event.issues.pinned
    async def _(event: events.IssuesPinned) -> None:
        issue = event.issue
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, "pinned {}"),
            issue_footer(issue),
            color="blue",
        )

    @webhook.event.issues.unpinned
    async def _(event: events.IssuesUnpinned) -> None:
        issue = event.issue
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, "unpinned {}"),
            issue_footer(issue),
            color="orange",
        )

    @webhook.event.issue_comment.created
    async def _(event: events.IssueCommentCreated) -> None:
        issue = event.issue
        title = "commented on "
        if issue.pull_request:
            entity = f"PR #{issue.number}"
            title += entity
            emoji = "pull_" + (
                ("merged" if issue.pull_request.merged_at else "closed")
                if issue.state == "closed"
                else ("draft" if issue.draft else "open")
            )
        else:
            entity = f"Issue #{issue.number}"
            title += entity.casefold()
            emoji = get_issue_emoji(cast("IssueLike", issue))

        footer = Footer(emoji, f"{entity}: {issue.title}")

        if vouch_command := find_vouch_command(event.comment.body):
            register_vouch_command(vouch_queue, vouch_command, event, footer)
            return

        await send_embed(
            bot,
            event.sender,
            EmbedContent(title, event.comment.html_url, event.comment.body),
            footer,
            origin_repo=event.repository,
        )
