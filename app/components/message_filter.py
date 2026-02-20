import re
from typing import TYPE_CHECKING, NamedTuple, cast, final

import discord as dc
from discord.ext import commands

from toolbox.discord import format_or_file, try_dm
from toolbox.messages import REGULAR_MESSAGE_TYPES

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.bot import GhosttyBot

URL_REGEX = re.compile(
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


class MessageFilterTuple(NamedTuple):
    channel_id: int
    filter: Callable[[dc.Message], object]
    template_fillers: tuple[str, str]


@final
class MessageFilter(commands.Cog):
    message_filters: tuple[MessageFilterTuple, ...]

    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

        self.message_filters = (
            # Delete non-image messages in #showcase
            MessageFilterTuple(
                self.bot.config.showcase_channel_id,
                lambda msg: cast("dc.Message", msg).attachments,
                ("any attachments", "a screenshot or a video"),
            ),
            # Delete non-link messages in #media
            MessageFilterTuple(
                self.bot.config.media_channel_id,
                lambda msg: URL_REGEX.search(cast("dc.Message", msg).content),
                ("a link", "a link"),
            ),
        )

    def check(self, message: dc.Message) -> MessageFilterTuple | None:
        """
        Returns the first message filter that did not pass, or None if all filters
        passed.
        """
        for msg_filter in self.message_filters:
            if message.channel.id == msg_filter.channel_id and not msg_filter.filter(
                message
            ):
                return msg_filter
        return None

    @commands.Cog.listener()
    async def on_message(self, message: dc.Message) -> None:
        if message.author == self.bot.user or not (msg_filter := self.check(message)):
            return
        assert isinstance(message.channel, dc.TextChannel)

        await message.delete()

        # Don't DM the user if it's a system message (e.g. "@user started a thread")
        if message.type not in REGULAR_MESSAGE_TYPES:
            return

        notification = _MESSAGE_DELETION_TEMPLATE.format(
            message.channel.mention, *msg_filter.template_fillers
        )
        if message.content:
            notification += _MESSAGE_CONTENT_NOTICE
        await try_dm(message.author, notification)

        if message.content:
            content, file = format_or_file(message.content)
            await try_dm(message.author, content, file=file, silent=True)
            await try_dm(message.author, _COPY_TEXT_HINT, silent=True)


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(MessageFilter(bot))
