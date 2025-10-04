"""
Replace discord social media links with <https://fxembed.com> replacements
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, final

import discord as dc
from discord.ext import commands

from app.common.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)

if TYPE_CHECKING:
    from app.bot import GhosttyBot

TWITTER_LINK = re.compile(r"https://(?:www\.)?(?:x|twitter)\.com/(\S+)")
BLUESKY_LINK = re.compile(r"https://(?:www\.)?bsky\.app/(\S+)")


@final
class FixUpActions(ItemActions):
    action_singular = "linked this social media post"
    action_plural = "linked these social media posts"


@final
class FixUp(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.linker = MessageLinker()
        FixUpActions.linker = self.linker

    async def process(self, message: dc.Message) -> ProcessedMessage:
        matches = [
            f"https://fixupx.com/{m.group(1)}"
            for m in TWITTER_LINK.finditer(message.content)
        ]
        matches.extend(
            f"https://fxbsky.app/{m.group(1)}"
            for m in BLUESKY_LINK.finditer(message.content)
        )
        if len(matches) > 5:
            # Discord will only display the first 5 link embeds
            matches = matches[:5]
            matches.append("-# Some links were omitted")
        return ProcessedMessage(content="\n".join(matches), item_count=len(matches))

    @commands.Cog.listener()
    async def on_message(self, message: dc.Message) -> None:
        if message.author.bot or self.bot.fails_message_filters(message):
            return
        output = await self.process(message)
        if output.item_count != 0:
            await message.edit(suppress=True)
        if output.item_count < 1:
            return

        sent_message = await message.reply(
            output.content,
            mention_author=False,
            allowed_mentions=dc.AllowedMentions.none(),
            view=FixUpActions(message, output.item_count),
        )
        self.linker.link(message, sent_message)
        await remove_view_after_delay(sent_message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=self.process,
            interactor=self.on_message,
            view_type=FixUpActions,
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(FixUp(bot))
