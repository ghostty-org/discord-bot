from typing import TYPE_CHECKING, Literal, Protocol, cast

from loguru import logger

from app.components.github_integration.models import GitHubUser
from app.components.github_integration.webhooks.utils import (
    VOUCH_KIND_COLORS,
    EmbedContent,
    Footer,
    send_embed,
)

if TYPE_CHECKING:
    from githubkit.versions.latest.models import DiscussionPropCategory, SimpleUser
    from monalisten import Monalisten, events

    from app.bot import EmojiName, GhosttyBot
    from app.components.github_integration.webhooks.utils import VouchQueue


class DiscussionLike(Protocol):
    title: str
    number: int
    html_url: str
    category: DiscussionPropCategory
    answer_html_url: str | None
    state: Literal["open", "closed", "locked", "converting", "transferring"]
    state_reason: Literal["resolved", "outdated", "duplicate", "reopened"] | None


def get_discussion_emoji(discussion: DiscussionLike) -> EmojiName:
    emoji = "discussion"
    if discussion.state_reason in ("outdated", "duplicate"):
        emoji += "_" + discussion.state_reason
    elif discussion.answer_html_url or discussion.state == "closed":
        emoji += "_answered"
    return emoji


def discussion_footer(
    discussion: DiscussionLike, *, emoji: EmojiName | None = None
) -> Footer:
    return Footer(
        emoji or get_discussion_emoji(discussion),
        f"Discussion #{discussion.number}: {discussion.title}",
    )


def discussion_embed_content(
    discussion: DiscussionLike, action: str, body: str | None = None
) -> EmbedContent:
    return EmbedContent(
        f"{action} discussion #{discussion.number} in {discussion.category.name}",
        discussion.html_url,
        body,
    )


def register_hooks(
    bot: GhosttyBot, webhook: Monalisten, vouch_queue: VouchQueue
) -> None:
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
            origin_repo=event.repository,
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
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "reopened"),
            discussion_footer(discussion),
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
            origin_repo=event.repository,
        )

    @webhook.event.discussion.unanswered
    async def _(event: events.DiscussionUnanswered) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender or cast("SimpleUser", GitHubUser.default()),
            discussion_embed_content(discussion, "unmarked an answer for"),
            discussion_footer(discussion),
            color="red",
            feed_type="discussions",
        )

    @webhook.event.discussion.locked
    async def _(event: events.DiscussionLocked) -> None:
        discussion = event.discussion
        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "locked"),
            discussion_footer(discussion),
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
        footer = discussion_footer(discussion)
        vouch_command = event.comment.body.removeprefix("!").partition(" ")[0]
        if vouch_command in VOUCH_KIND_COLORS:
            logger.info(
                "ignoring vouch system comment from @{} in #{}",
                event.sender.login,
                discussion.number,
            )
            vouch_queue[event.comment.id] = vouch_command, event.sender, footer
            return

        await send_embed(
            bot,
            event.sender,
            discussion_embed_content(discussion, "commented on", event.comment.body),
            footer,
            feed_type="discussions",
            origin_repo=event.repository,
        )
