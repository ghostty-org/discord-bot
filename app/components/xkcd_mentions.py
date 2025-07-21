import asyncio
import datetime as dt
import re

import discord as dc
import httpx
from pydantic import BaseModel

from app.common.cache import TTRCache
from app.common.hooks import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)

XKCD_REGEX = re.compile(r"\bxkcd#(\d+)", re.IGNORECASE)
XKCD_URL = "https://xkcd.com/{}"


class XKCD(BaseModel):
    day: int
    month: int
    year: int
    img: str
    title: str
    alt: str


class XKCDMentionCache(TTRCache[int, dc.Embed]):
    async def fetch(self, key: int) -> None:
        url = XKCD_URL.format(key)
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{url}/info.0.json")
        if not resp.is_success:
            error = (
                f"xkcd #{key} does not exist."
                if resp.status_code == 404
                else f"Unable to fetch xkcd #{key}."
            )
            self[key] = dc.Embed(color=dc.Color.red()).set_footer(text=error)
            return

        xkcd = XKCD(**resp.json())
        date = dt.datetime(
            day=xkcd.day, month=xkcd.month, year=xkcd.year, tzinfo=dt.UTC
        )
        self[key] = (
            dc.Embed(title=xkcd.title, url=url)
            .set_image(url=xkcd.img)
            .set_footer(text=f"{xkcd.alt} • {date:%B %-d, %Y}")
        )


xkcd_mention_cache = XKCDMentionCache(hours=12)
xkcd_mention_linker = MessageLinker()


class XKCDActions(ItemActions):
    linker = xkcd_mention_linker
    action_singular = "linked this xkcd comic"
    action_plural = "linked these xkcd comics"


async def xkcd_mention_message(message: dc.Message) -> ProcessedMessage:
    embeds = []
    matches = list(dict.fromkeys(m[1] for m in XKCD_REGEX.finditer(message.content)))
    omitted = None
    if len(matches) > 10:
        omitted = dc.Embed(color=dc.Color.orange()).set_footer(
            text=f"{len(matches) - 9} xkcd comics were omitted."
        )
        # Nine instead of ten to account for the `omitted` embed.
        matches = matches[:9]
    embeds = await asyncio.gather(*(xkcd_mention_cache.get(int(m)) for m in matches))
    if omitted:
        embeds.append(omitted)
    return ProcessedMessage(embeds=embeds, item_count=len(embeds))


async def handle_xkcd_mentions(message: dc.Message) -> None:
    if message.author.bot:
        return
    output = await xkcd_mention_message(message)
    if output.item_count < 1:
        return
    try:
        sent_message = await message.reply(
            embeds=output.embeds,
            mention_author=False,
            view=XKCDActions(message, output.item_count),
        )
    except dc.HTTPException:
        return
    xkcd_mention_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


xkcd_mention_delete_hook = create_delete_hook(linker=xkcd_mention_linker)

xkcd_mention_edit_hook = create_edit_hook(
    linker=xkcd_mention_linker,
    message_processor=xkcd_mention_message,
    interactor=handle_xkcd_mentions,
    view_type=XKCDActions,
)
