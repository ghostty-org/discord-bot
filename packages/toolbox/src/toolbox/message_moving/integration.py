import asyncio
import datetime as dt
from functools import partial
from typing import Literal, overload

import discord as dc

from .conversion import (
    convert_nitro_emojis,
    format_forward,
    format_interaction,
    get_reply_embed,
    get_sticker_embed,
)
from .moved_message import MovedMessage
from .subtext import SplitSubtext, Subtext
from toolbox.discord import format_or_file
from toolbox.messages import (
    BOT_COMMAND_MESSAGE_TYPES,
    REGULAR_MESSAGE_TYPES,
    MessageData,
)


def message_can_be_moved(message: dc.Message) -> bool:
    return (
        message.guild is not None
        and message.type in REGULAR_MESSAGE_TYPES | BOT_COMMAND_MESSAGE_TYPES
    )


async def get_or_create_webhook(
    channel: dc.TextChannel | dc.ForumChannel, name: str = "Ghostty Moderator"
) -> dc.Webhook:
    webhooks = await channel.webhooks()
    for webhook in webhooks:
        if webhook.name == name:
            if webhook.token is None:
                await webhook.delete()
            else:
                return webhook

    return await channel.create_webhook(name=name)


@overload
async def move_message(
    client: dc.Client,
    webhook: dc.Webhook,
    message: dc.Message,
    executor: dc.Member | None = None,
    *,
    thread: dc.abc.Snowflake = dc.utils.MISSING,
    thread_name: str = dc.utils.MISSING,
    include_move_marks: Literal[True] = True,
) -> MovedMessage: ...


@overload
async def move_message(
    client: dc.Client,
    webhook: dc.Webhook,
    message: dc.Message,
    executor: dc.Member | None = None,
    *,
    thread: dc.abc.Snowflake = dc.utils.MISSING,
    thread_name: str = dc.utils.MISSING,
    include_move_marks: Literal[False] = False,
) -> dc.WebhookMessage: ...


async def move_message(  # noqa: PLR0913
    client: dc.Client,
    webhook: dc.Webhook,
    message: dc.Message,
    executor: dc.Member | None = None,
    *,
    thread: dc.abc.Snowflake = dc.utils.MISSING,
    thread_name: str = dc.utils.MISSING,
    include_move_marks: bool = True,
) -> MovedMessage | dc.WebhookMessage:
    """
    WARNING: it is the caller's responsibility to check message_can_be_moved() and to
    display an informative error message.
    """
    if not message_can_be_moved(message):
        msg = "message_can_be_moved must be checked by caller"
        raise AssertionError(msg)
    assert message.guild is not None

    msg_data = await MessageData.scrape(message)

    embeds = [
        *(e for e in message.embeds if not e.url),
        *await asyncio.gather(*map(get_sticker_embed, message.stickers)),
    ]

    if message.message_snapshots:
        # Only include the first message snapshot.
        snapshot = message.message_snapshots[0]
        forward_embeds, forward_attachments = await format_forward(
            client, message.guild, snapshot
        )
        embeds = [*forward_embeds, *embeds]
        msg_data.files.extend(forward_attachments)
    elif reply_embed := await get_reply_embed(message):
        embeds.append(reply_embed)

    if (
        message.poll is None
        # Discord does not like polls with a negative duration. Polls created by
        # a webhook cannot be ended manually, so simply discard polls which have ended.
        or message.poll.expires_at is None
        or dt.datetime.now(tz=dt.UTC) >= message.poll.expires_at
    ):
        poll = dc.utils.MISSING
    else:
        poll = message.poll

    if include_move_marks and isinstance(
        moved_message := await MovedMessage.from_message(message), MovedMessage
    ):
        # Append the new move mark to the existing subtext.
        split_subtext = SplitSubtext(moved_message)
        split_subtext.update(message, executor)
        message.content, subtext = split_subtext.content, split_subtext.subtext
    else:
        # The if expression skips the poll ended message if there was no poll.
        s = Subtext(msg_data, executor, poll if message.poll is not None else None)
        subtext = s.format() if include_move_marks else s.format_simple()

    content, file = format_or_file(
        format_interaction(message),
        template=f"{{}}\n{subtext}",
        transform=partial(convert_nitro_emojis, client, message.guild),
    )
    if file:
        msg_data.files.append(file)
        if not content.strip():
            content = "-# Content attached"
        elif "•" in content:
            # Ensure the move mark stays at the end, so that appending to the move mark
            # later in SplitSubtext.update() doesn't make the result incorrect.
            subtext, _, move_mark = content.rpartition(" • ")
            content = f"{subtext} • Content attached • {move_mark}"
        else:
            content += " • Content attached"

    msg = await webhook.send(
        content=content,
        poll=poll,
        username=message.author.display_name,
        avatar_url=message.author.display_avatar.url,
        allowed_mentions=dc.AllowedMentions.none(),
        files=msg_data.files,
        embeds=embeds,
        thread=thread,
        thread_name=thread_name,
        wait=True,
    )
    await message.delete()

    # Even though `message` is definitely from a guild, not all messages have a Member
    # as its author. A notable example is WebhookMessage, whose author is the webhook,
    # which is a User and not a Member. This means that we cannot assert message.author
    # to be a Member since that would fail when moving a moved message.
    author = message.author if isinstance(message.author, dc.Member) else None
    # This never throws as the subtext has the author present if including move marks
    # (see above).
    return MovedMessage(msg, author=author) if include_move_marks else msg
