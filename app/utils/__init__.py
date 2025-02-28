from __future__ import annotations

import asyncio
import datetime as dt
from collections import defaultdict
from contextlib import suppress
from textwrap import shorten
from typing import TYPE_CHECKING, Any

import discord

from app.setup import config

from .message_data import MessageData, scrape_message_data
from .webhooks import (
    GuildTextChannel,
    format_or_file,
    get_or_create_webhook,
    move_message_via_webhook,
)

__all__ = (
    "Account",
    "GuildTextChannel",
    "MessageData",
    "MessageLinker",
    "format_or_file",
    "get_or_create_webhook",
    "is_dm",
    "is_helper",
    "is_mod",
    "move_message_via_webhook",
    "remove_view_after_timeout",
    "scrape_message_data",
    "try_dm",
)

if TYPE_CHECKING:
    from typing_extensions import TypeIs


type Account = discord.User | discord.Member


class MessageLinker:
    def __init__(self) -> None:
        self._refs = defaultdict[discord.Message, list[discord.Message]](list)

    def get(self, original: discord.Message) -> list[discord.Message]:
        return self._refs[original]

    def link(self, original: discord.Message, *replies: discord.Message) -> None:
        self._refs[original].extend(replies)

    def unlink(self, original: discord.Message) -> None:
        del self._refs[original]

    def get_original_message(self, reply: discord.Message) -> discord.Message | None:
        return next(
            (msg for msg, replies in self._refs.items() if reply in replies), None
        )

    def unlink_from_reply(self, reply: discord.Message) -> None:
        if (original_message := self.get_original_message(reply)) is not None:
            self.unlink(original_message)

    def unlink_if_expired(self, reply: discord.Message) -> bool:
        # Stop reacting to message updates after 24 hours
        last_updated = reply.edited_at or reply.created_at
        if dt.datetime.now(tz=dt.UTC) - last_updated > dt.timedelta(hours=24):
            self.unlink_from_reply(reply)
            return True
        return False


def is_dm(account: Account) -> TypeIs[discord.User]:
    return not isinstance(account, discord.Member)


def is_mod(member: discord.Member) -> bool:
    return member.get_role(config.MOD_ROLE_ID) is not None


def is_helper(member: discord.Member) -> bool:
    return member.get_role(config.HELPER_ROLE_ID) is not None


async def try_dm(account: Account, content: str, **extras: Any) -> None:
    if account.bot:
        return
    try:
        await account.send(content, **extras)
    except discord.Forbidden:
        print(f"Failed to DM {account} with: {shorten(content, width=50)}")


async def remove_view_after_timeout(
    message: discord.Message,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> None:
    await asyncio.sleep(timeout)
    with suppress(discord.NotFound, discord.HTTPException):
        await message.edit(view=None)


def dynamic_timestamp(dt: dt.datetime, fmt: str | None = None) -> str:
    fmt = f":{fmt}" if fmt is not None else ""
    return f"<t:{int(dt.timestamp())}{fmt}>"
