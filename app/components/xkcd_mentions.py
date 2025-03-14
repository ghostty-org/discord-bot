import asyncio
import re

import discord

from app.utils import (
    DeleteMessage,
    MessageLinker,
    TTRCache,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)

XKCD_REGEX = re.compile(r"\bxkcd#(\d+)", re.IGNORECASE)


class XKCDMentionCache(TTRCache[int, str]):
    async def fetch(self, key: int) -> None:
        self[key] = f"https://xkcd.com/{key}"


xkcd_mention_cache = XKCDMentionCache(hours=12)
xkcd_mention_linker = MessageLinker()


class DeleteXKCDMention(DeleteMessage):
    linker = xkcd_mention_linker
    action_singular = "linked this XKCD comic"
    action_plural = "linked these XKCD comics"


async def xkcd_mention_message(message: discord.Message) -> tuple[str, int]:
    matches = (
        xkcd_mention_cache.get(int(m[1])) for m in XKCD_REGEX.finditer(message.content)
    )
    resp = await asyncio.gather(*matches)
    return "\n".join(resp), len(resp)


async def handle_xkcd_mentions(message: discord.Message) -> None:
    if message.author.bot:
        return
    content, count = await xkcd_mention_message(message)
    if count < 1:
        return
    try:
        sent_message = await message.reply(
            content, mention_author=False, view=DeleteXKCDMention(message, count)
        )
    except discord.HTTPException:
        return
    xkcd_mention_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


xkcd_mention_delete_hook = create_delete_hook(linker=xkcd_mention_linker)

xkcd_mention_edit_hook = create_edit_hook(
    linker=xkcd_mention_linker,
    message_processor=xkcd_mention_message,
    interactor=handle_xkcd_mentions,
    view_type=DeleteXKCDMention,
)
