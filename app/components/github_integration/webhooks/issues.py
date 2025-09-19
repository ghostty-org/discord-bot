from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Any, Protocol, cast, final, override

from discord.ext import commands
from loguru import logger

from app.components.github_integration.webhooks.core import (
    EmbedContent,
    Footer,
    send_embed,
)
from app.components.github_integration.webhooks.core import client as monalisten_client

if TYPE_CHECKING:
    from githubkit.typing import Missing
    from monalisten import Monalisten, events

    from app.bot import EmojiName, GhosttyBot

CONVERTED_DISCUSSION_HEADER = re.compile(
    r"\s*### Discussed in https://github.com/.*?/discussions/(?P<discussion_number>\d+)"
    r"\s*<div type='discussions-op-text'>"
    r"\s*<sup>(?P<subtext>.+?)</sup>",
    re.MULTILINE,
)


def reformat_converted_discussion_header(body: str | None, repo_url: str) -> str | None:
    if body is None or not (match := CONVERTED_DISCUSSION_HEADER.match(body)):
        return body

    d, subtext = match["discussion_number"], match["subtext"]
    new_heading = f"### Discussed in [#{d}]({repo_url}/discussions/{d})\n-# {subtext}\n"

    _, end = match.span()
    return new_heading + "".join(body[end:].lstrip().rsplit("</div>", maxsplit=1))


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


def issue_footer(issue: IssueLike, *, emoji: EmojiName | None = None) -> Footer:
    return Footer(
        emoji or get_issue_emoji(issue), f"Issue #{issue.number}: {issue.title}"
    )


def issue_embed_content(
    issue: IssueLike, template: str, body: str | None = None
) -> EmbedContent:
    return EmbedContent(template.format(f"issue #{issue.number}"), issue.html_url, body)


@final
class Issues(commands.Cog):
    def __init__(self, bot: GhosttyBot, monalisten_client: Monalisten) -> None:
        self.bot = bot
        self.monalisten_client = monalisten_client

    @override
    async def cog_load(self) -> None:
        register_hooks(self.bot, self.monalisten_client)


def register_hooks(bot: GhosttyBot, webhook: Monalisten) -> None:  # noqa: PLR0915
    @webhook.event.issues.opened
    async def _(event: events.IssuesOpened) -> None:
        issue = event.issue
        body = reformat_converted_discussion_header(
            issue.body, event.repository.html_url
        )
        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, "opened {}", body),
            issue_footer(issue, emoji="issue_open"),
            color="green",
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
        issue, changes = event.issue, event.changes

        if issue.created_at > dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=15):
            return

        update_notes: list[str] = []
        if changes.title:
            update_notes.append(
                f'Renamed from "{changes.title.from_}" to "{issue.title}"'
            )
        if changes.body:
            update_notes.append("Updated description")

        match update_notes:
            case [note]:
                content = note
            case [note1, note2]:
                content = f"* {note1}\n* {note2}"
            case _:
                return

        await send_embed(
            bot,
            event.sender,
            issue_embed_content(issue, "edited {}", content),
            issue_footer(issue),
        )

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

        await send_embed(
            bot,
            event.sender,
            EmbedContent(title, event.comment.html_url, event.comment.body),
            Footer(emoji, f"{entity}: {issue.title}"),
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(Issues(bot, monalisten_client))
