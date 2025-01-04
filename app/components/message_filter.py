import re
from collections.abc import Callable
from typing import NamedTuple

import discord

from app.setup import config
from app.utils import try_dm

URL_REGEX = re.compile(
    r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)
MESSAGE_DELETION_TEMPLATE = (
    "Hey! Your message in {} was deleted because it did not contain {}."
    " Make sure to include {}, and respond in threads."
)
REGULAR_MESSAGE_TYPES = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)


class MessageFilter(NamedTuple):
    channel_id: int
    filter: Callable[[discord.Message], object]
    template_fillers: tuple[str, str]


MESSAGE_FILTERS = (
    # Delete non-image messages in #showcase
    MessageFilter(
        config.SHOWCASE_CHANNEL_ID,
        lambda msg: msg.attachments,
        ("any attachments", "a screenshot or a video"),
    ),
    # Delete non-link messages in #media
    MessageFilter(
        config.MEDIA_CHANNEL_ID,
        lambda msg: URL_REGEX.search(msg.content),
        ("a link", "a link"),
    ),
)


async def check_message_filters(message: discord.Message) -> bool:
    for msg_filter in MESSAGE_FILTERS:
        if message.channel.id != msg_filter.channel_id or msg_filter.filter(message):
            continue
        await message.delete()
        if message.type not in REGULAR_MESSAGE_TYPES:
            continue
        assert isinstance(message.channel, discord.TextChannel)
        await try_dm(
            message.author,
            MESSAGE_DELETION_TEMPLATE.format(
                message.channel.mention, *msg_filter.template_fillers
            ),
        )
        return True
    return False
