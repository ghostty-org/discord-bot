import re
from contextlib import suppress

import discord

XKCD_REGEX = re.compile(r"xkcd\#(\d+)")


async def handle_xkcd_mentions(message: discord.Message) -> None:
    if resp := "\n".join(
        f"https://xkcd.com/{m[1]}" for m in XKCD_REGEX.finditer(message.content)
    ):
        with suppress(discord.HTTPException):
            await message.reply(resp, mention_author=False)
