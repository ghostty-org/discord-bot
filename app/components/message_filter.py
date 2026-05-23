from typing import TYPE_CHECKING, NamedTuple, cast, final

import discord as dc
from discord.ext import commands

from app.config import config
from toolbox.discord import GuildTextChannel, format_or_file, try_dm
from toolbox.messages import REGULAR_MESSAGE_TYPES
from toolbox.misc import URL_REGEX

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.bot import GhosttyBot

_MESSAGE_DELETION_TEMPLATE = (
    "Hey! Your message in {channel} was deleted because it did not contain "
    "{requirement}. Make sure to include {suggestion}, and respond in threads.\n"
)
_MESSAGE_CONTENT_NOTICE = "Here's the message you tried to send:"
_COPY_TEXT_HINT = (
    "-# **Hint:** you can get your original message with formatting preserved "
    'by using the "Copy Text" action in the context menu.'
)


class MessageFilterTuple(NamedTuple):
    channel_id: int
    filter: Callable[[dc.Message], object]
    requirement: str
    suggestion: str


@final
class MessageFilter(commands.Cog):
    message_filters: tuple[MessageFilterTuple, ...]

    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

        self.message_filters = (
            # Delete non-image messages in #showcase
            MessageFilterTuple(
                config().channel_ids.showcase,
                lambda msg: cast("dc.Message", msg).attachments,
                requirement="any attachments",
                suggestion="a screenshot or a video",
            ),
            # Delete non-link messages in #media
            MessageFilterTuple(
                config().channel_ids.media,
                lambda msg: URL_REGEX.search(cast("dc.Message", msg).content),
                requirement="a link",
                suggestion="a link",
            ),
        )

    def check(self, message: dc.Message) -> MessageFilterTuple | None:
        """
        Returns the first message filter that did not pass, or `None` if all filters
        passed.
        """
        assert isinstance(message.channel, GuildTextChannel)
        return self.check_in(message.channel, message)

    def check_in(
        self, channel: GuildTextChannel, message: dc.Message
    ) -> MessageFilterTuple | None:
        """
        Returns the first message filter that would not pass were `message` to be sent
        in `channel`, or `None` if all filters passed.
        """
        for msg_filter in self.message_filters:
            if channel.id == msg_filter.channel_id and not msg_filter.filter(message):
                return msg_filter
        return None

    @commands.Cog.listener()
    async def on_message(self, message: dc.Message) -> None:
        if (
            message.guild is None
            or message.author == self.bot.user
            or not (failing_filter := self.check(message))
        ):
            return
        assert isinstance(message.channel, dc.TextChannel)

        await message.delete()

        # Don't DM the user if it's a system message (e.g. "@user started a thread")
        if message.type not in REGULAR_MESSAGE_TYPES:
            return

        notification = _MESSAGE_DELETION_TEMPLATE.format(
            channel=message.channel.mention,
            requirement=failing_filter.requirement,
            suggestion=failing_filter.suggestion,
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
