from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple, cast, final

import discord as dc
from discord.ext import commands

from app.utils import format_or_file, try_dm

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.bot import GhosttyBot

_URL_REGEX = re.compile(
    r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b"
    r"(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)
_MESSAGE_DELETION_TEMPLATE = (
    "Hey! Your message in {} was deleted because it did not contain {}. "
    "Make sure to include {}, and respond in threads.\n"
)
_MESSAGE_CONTENT_NOTICE = "Here's the message you tried to send:"
_COPY_TEXT_HINT = (
    "-# **Hint:** you can get your original message with formatting preserved "
    'by using the "Copy Text" action in the context menu.'
)
_REGULAR_MESSAGE_TYPES = frozenset({dc.MessageType.default, dc.MessageType.reply})


class _MessageFilterTuple(NamedTuple):
    channel_id: int
    filter: Callable[[dc.Message], object]
    template_fillers: tuple[str, str]


@final
class MessageFilter(commands.Cog):
    message_filters: tuple[_MessageFilterTuple, ...]

    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

        self.message_filters = (
            # Delete non-image messages in #showcase
            _MessageFilterTuple(
                self.bot.config.showcase_channel_id,
                lambda msg: cast("dc.Message", msg).attachments,
                ("any attachments", "a screenshot or a video"),
            ),
            # Delete non-link messages in #media
            _MessageFilterTuple(
                self.bot.config.media_channel_id,
                lambda msg: _URL_REGEX.search(cast("dc.Message", msg).content),
                ("a link", "a link"),
            ),
        )

    @commands.Cog.listener("on_message")
    async def check_message_filters(self, message: dc.Message) -> None:
        if message.author == self.bot.user:
            return
        for msg_filter in self.message_filters:
            if message.channel.id != msg_filter.channel_id or msg_filter.filter(
                message
            ):
                continue

            await message.delete()

            # Don't DM the user if it's a system message (e.g. "@user started a thread")
            if message.type not in _REGULAR_MESSAGE_TYPES:
                continue

            assert isinstance(message.channel, dc.TextChannel)

            notification = _MESSAGE_DELETION_TEMPLATE.format(
                message.channel.mention, *msg_filter.template_fillers
            )
            if content_size := len(message.content):
                notification += _MESSAGE_CONTENT_NOTICE
            await try_dm(message.author, notification, silent=content_size > 0)

            if content_size > 0:
                content, file = format_or_file(message.content)
                await try_dm(message.author, content, file=file)
                await try_dm(message.author, _COPY_TEXT_HINT, silent=True)

            return


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(MessageFilter(bot))
