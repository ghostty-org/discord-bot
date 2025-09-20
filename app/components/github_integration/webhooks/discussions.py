from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, cast, final, override

from discord.ext import commands

from app.components.github_integration.models import GitHubUser
from app.components.github_integration.webhooks.core import (
    EmbedContent,
    Footer,
    send_embed,
)

if TYPE_CHECKING:
    from githubkit.versions.latest.models import DiscussionPropCategory, SimpleUser
    from monalisten import Monalisten, events

    from app.bot import EmojiName, GhosttyBot


class DiscussionLike(Protocol):
    title: str
    number: int
    html_url: str
    category: DiscussionPropCategory
    answer_html_url: str | None
    state: Literal["open", "closed", "locked", "converting", "transferring"]


def discussion_footer(
    discussion: DiscussionLike, *, emoji: EmojiName | None = None
) -> Footer:
    emoji = emoji or (
        "discussion_answered"
        if discussion.answer_html_url or discussion.state == "closed"
        else "discussion"
    )
    return Footer(emoji, f"Discussion #{discussion.number}: {discussion.title}")


def discussion_embed_content(
    discussion: DiscussionLike, action: str, body: str | None = None
) -> EmbedContent:
    return EmbedContent(
        f"{action} discussion #{discussion.number} in {discussion.category.name}",
        discussion.html_url,
        body,
    )


@final
class Discussions(commands.Cog):
    def __init__(self, bot: GhosttyBot, monalisten_client: Monalisten) -> None:
        self.bot = bot
        self.monalisten_client = monalisten_client

    @override
    async def cog_load(self) -> None:
        register_hooks(self.bot, self.monalisten_client)


def register_hooks(bot: GhosttyBot, webhook: Monalisten) -> None:
    @webhook.event.discussion.created
    async def _(event: events.DiscussionCreated) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "opened", discussion.body),
            discussion_footer(discussion, emoji="discussion"),
            color="gray",
            feed_type="discussions",
        )

    @webhook.event.discussion.closed
    async def _(event: events.DiscussionClosed) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "closed"),
            discussion_footer(discussion, emoji="discussion_answered"),
            color="purple",
            feed_type="discussions",
        )

    @webhook.event.discussion.reopened
    async def _(event: events.DiscussionReopened) -> None:
        discussion = event.discussion
        emoji = "discussion_answered" if discussion.answer_html_url else "discussion"
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "reopened"),
            discussion_footer(discussion, emoji=emoji),
            color="gray",
            feed_type="discussions",
        )

    @webhook.event.discussion.answered
    async def _(event: events.DiscussionAnswered) -> None:
        discussion = event.discussion
        if answering_user := event.answer.user:
            gh_user = GitHubUser(**answering_user.model_dump())
            body = f"-# Answer by {gh_user.hyperlink}"
        else:
            body = None
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "chose an answer for", body),
            discussion_footer(discussion, emoji="discussion_answered"),
            color="green",
            feed_type="discussions",
        )

    @webhook.event.discussion.unanswered
    async def _(event: events.DiscussionUnanswered) -> None:
        discussion = event.discussion
        emoji = "discussion_answered" if discussion.state == "closed" else "discussion"
        await send_embed(
            bot,
            event.sender or cast("SimpleUser", GitHubUser.default()),
            discussion_embed_content(discussion, "unmarked an answer for"),
            discussion_footer(discussion, emoji=emoji),
            color="red",
            feed_type="discussions",
        )

    @webhook.event.discussion.locked
    async def _(event: events.DiscussionLocked) -> None:
        discussion = event.discussion
        emoji = "discussion_answered" if discussion.answer_html_url else "discussion"
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "locked"),
            discussion_footer(discussion, emoji=emoji),
            color="orange",
            feed_type="discussions",
        )

    @webhook.event.discussion.unlocked
    async def _(event: events.DiscussionUnlocked) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "unlocked"),
            discussion_footer(discussion),
            color="blue",
            feed_type="discussions",
        )

    @webhook.event.discussion.pinned
    async def _(event: events.DiscussionPinned) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "pinned"),
            discussion_footer(discussion),
            color="blue",
            feed_type="discussions",
        )

    @webhook.event.discussion.unpinned
    async def _(event: events.DiscussionUnpinned) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "unpinned"),
            discussion_footer(discussion),
            color="orange",
            feed_type="discussions",
        )

    @webhook.event.discussion_comment.created
    async def _(event: events.DiscussionCommentCreated) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "commented on", event.comment.body),
            discussion_footer(discussion),
            feed_type="discussions",
        )
