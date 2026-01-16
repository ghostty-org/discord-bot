# PPE is strongly recommended in this file. Blindfolds are even better.

import asyncio
import itertools
from contextlib import suppress
from typing import Self

import discord as dc
from loguru import logger

__all__ = (
    "MAX_ATTACHMENT_SIZE",
    "ExtensibleMessage",
    "MessageData",
    "get_files",
)

MAX_ATTACHMENT_SIZE = 67_108_864  # 64 MiB


class ExtensibleMessage(dc.Message):
    """
    This class is intended to be subclassed when wanting a constructor that uses the
    state from an existing Message instead of constructing a new one with
    Message.__init__().
    """

    def __init__(self, message: dc.Message) -> None:  # pyright: ignore[reportMissingSuperCall]
        for attr in itertools.chain.from_iterable(
            getattr(cls, "__slots__", ()) for cls in type(message).__mro__
        ):
            with suppress(AttributeError):
                # At the time of writing, the only things which cause an AttributeError
                # to be thrown are `call` and everything that starts with `_cs_`.
                setattr(self, attr, getattr(message, attr))


async def get_files(attachments: list[dc.Attachment]) -> tuple[list[dc.File], int]:
    """
    It's usually a better idea to use MessageData.scrape() instead. Only use this
    function if you do not have a Message.
    """
    files = await asyncio.gather(
        *(a.to_file() for a in attachments if a.size <= MAX_ATTACHMENT_SIZE)
    )
    skipped_attachments = len(attachments) - len(files)
    return files, skipped_attachments


class MessageData(ExtensibleMessage):
    files: list[dc.File]  # pyright: ignore[reportUninitializedInstanceVariable]
    skipped_attachments: int  # pyright: ignore[reportUninitializedInstanceVariable]

    @classmethod
    async def scrape(cls, message: dc.Message) -> Self:
        # This code cannot go in __init__ as it is async.
        logger.debug("scraping message {}", message)
        msg_data = cls(message)
        msg_data.files, msg_data.skipped_attachments = await get_files(
            message.attachments
        )
        return msg_data
