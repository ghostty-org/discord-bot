# PPE is strongly recommended in this file. Blindfolds are even better.

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Self

import discord

MAX_ATTACHMENT_SIZE = 67_108_864  # 64 MiB


class ExtensibleMessage(discord.Message):
    """
    This class is intended to be subclassed when wanting a constructor that
    uses the state from an existing Message instead of constructing a new one
    with Message.__init__().
    """

    def __init__(self, message: discord.Message) -> None:
        # Message doesn't expose a __dict__ that we can update() onto our
        # __dict__, so use dir() to manually add them all.
        for attr in dir(message):
            val = getattr(type(self), attr)
            if (
                # Don't break the class.
                attr == "__class__"
                # Already acquired by the subclass declaration.
                or isinstance(val, property)
                or callable(val)
            ):
                continue
            with suppress(AttributeError):
                # At the time of writing, the only things which cause an
                # AttributeError to be thrown are `call` and everything that
                # starts with `_cs_`.
                setattr(self, attr, getattr(message, attr))


class MessageData(ExtensibleMessage):
    @classmethod
    async def scrape(cls, message: discord.Message) -> Self:
        # This code cannot go in __init__ as it is async.
        msg_data = cls(message)
        await msg_data._get_files(message.attachments)
        return msg_data

    async def _get_files(self, attachments: list[discord.Attachment]) -> None:
        self.files = await asyncio.gather(
            *(a.to_file() for a in attachments if a.size <= MAX_ATTACHMENT_SIZE)
        )
        self.skipped_attachments = len(attachments) - len(self.files)
