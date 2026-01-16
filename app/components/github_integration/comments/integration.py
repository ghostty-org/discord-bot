import asyncio
from typing import TYPE_CHECKING, final, override

import discord as dc
from discord.ext import commands

from .fetching import get_comments
from app.components.github_integration.entities.cache import entity_cache
from app.components.github_integration.entities.fmt import get_entity_emoji
from toolbox.discord import suppress_embeds_after_delay
from toolbox.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)

if TYPE_CHECKING:
    from app.bot import GhosttyBot
    from app.components.github_integration.models import Comment

REACTION_EMOJIS = {
    "plus_one": "👍",
    "minus_one": "👎",
    "laugh": "😄",  # NOTE: while laugh is actually 😆, GitHub's UI uses smile.
    "confused": "😕",
    "heart": "❤️",  # test: allow-vs16
    "hooray": "🎉",
    "eyes": "👀",
    "rocket": "🚀",
}

_FIGURE_SPACE = "\u2007"


@final
class CommentActions(ItemActions):
    action_singular = "linked this comment"
    action_plural = "linked these comments"


@final
class GitHubComments(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        entity_cache.register_gh(self, self.bot.gh)
        self.linker = MessageLinker()
        CommentActions.linker = self.linker

    @override
    async def cog_unload(self) -> None:
        entity_cache.unregister_gh(self)

    def comment_to_embed(self, comment: Comment) -> dc.Embed:
        emoji = get_entity_emoji(self.bot.ghostty_emojis, comment.entity)
        title = f"{emoji} {comment.entity.title}"
        formatted_reactions = comment.reactions and [
            f"{REACTION_EMOJIS[reaction]} ×{count}"  # noqa: RUF001
            for reaction, count in comment.reactions
            if count
        ]
        embed = (
            dc
            .Embed(
                description=comment.body,
                title=title,
                url=comment.html_url,
                timestamp=comment.created_at,
                color=comment.color,
            )
            .set_author(**comment.author.model_dump())
            .set_footer(text=f"{comment.kind} on {comment.entity_gist}")
        )
        if formatted_reactions:
            embed.add_field(
                # Discord collapses multiple spaces, so a figure space (which is one of
                # the ones which don't seem to be collapsed) has to be used instead of
                # multiple adjacent spaces.
                name="",
                value="-# " + f" {_FIGURE_SPACE} ".join(formatted_reactions),
            )
        return embed

    @commands.Cog.listener("on_message_filter_passed")
    async def reply_with_comments(self, message: dc.Message) -> None:
        embeds = [
            self.comment_to_embed(comment)
            async for comment in get_comments(message.content)
        ]
        if not embeds:
            return
        if len(embeds) > 10:
            omitted = len(embeds) - 10
            note = f"{omitted} comment{'s were' if omitted > 1 else ' was'} omitted"
            embeds = embeds[:10]
        else:
            note = None
        sent_message = await message.reply(
            content=note,
            embeds=embeds,
            mention_author=False,
            view=CommentActions(message, len(embeds)),
        )
        await message.edit(suppress=True)
        self.linker.link(message, sent_message)
        async with asyncio.TaskGroup() as group:
            group.create_task(suppress_embeds_after_delay(message))
            group.create_task(remove_view_after_delay(sent_message))

    async def process(self, msg: dc.Message) -> ProcessedMessage:
        comments = [self.comment_to_embed(i) async for i in get_comments(msg.content)]
        return ProcessedMessage(embeds=comments, item_count=len(comments))

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=self.process,
            interactor=self.reply_with_comments,
            view_type=CommentActions,
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(GitHubComments(bot))
