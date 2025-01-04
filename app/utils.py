from __future__ import annotations

import io
from textwrap import shorten
from typing import TYPE_CHECKING, NamedTuple

import discord

from app.setup import config

if TYPE_CHECKING:
    from collections.abc import Callable

    from typing_extensions import TypeIs

MAX_ATTACHMENT_SIZE = 67_108_864  # 64 MiB

SERVER_ONLY = discord.app_commands.allowed_contexts(
    guilds=True, dms=False, private_channels=False
)

Account = discord.User | discord.Member
GuildTextChannels = discord.TextChannel | discord.ForumChannel | discord.Thread


class MessageData(NamedTuple):
    content: str
    channel: discord.abc.MessageableChannel
    attachments: list[discord.File]
    skipped_attachments: int
    reactions: dict[str | discord.Emoji, int]


async def scrape_message_data(message: discord.Message) -> MessageData:
    return MessageData(
        message.content,
        message.channel,
        *await _get_attachments(message),
        _get_reactions(message),
    )


async def _get_attachments(message: discord.Message) -> tuple[list[discord.File], int]:
    if not message.attachments:
        return [], 0

    attachments: list[discord.File] = []
    skipped_attachments = 0
    for attachment in message.attachments:
        if attachment.size > MAX_ATTACHMENT_SIZE:
            skipped_attachments += 1
            continue

        fp = io.BytesIO(await attachment.read())
        attachments.append(discord.File(fp, filename=attachment.filename))

    return attachments, skipped_attachments


def _get_reactions(message: discord.Message) -> dict[str | discord.Emoji, int]:
    reactions: dict[str | discord.Emoji, int] = {}
    for reaction in message.reactions:
        if isinstance(emoji := reaction.emoji, discord.Emoji) and not emoji.is_usable():
            continue
        if isinstance(emoji, discord.PartialEmoji):
            continue
        reactions[emoji] = reaction.count
    return reactions


def _format_subtext(executor: discord.Member | None, msg_data: MessageData) -> str:
    lines: list[str] = []
    if reactions := msg_data.reactions.items():
        lines.append("   ".join(f"{emoji} x{count}" for emoji, count in reactions))
    if executor:
        assert isinstance(msg_data.channel, GuildTextChannels)
        lines.append(f"Moved from {msg_data.channel.mention} by {executor.mention}")
    if skipped := msg_data.skipped_attachments:
        lines.append(f"(skipped {skipped} large attachment(s))")
    return "".join(f"\n-# {line}" for line in lines)


async def get_or_create_webhook(
    name: str, channel: discord.TextChannel | discord.ForumChannel
) -> discord.Webhook:
    webhooks = await channel.webhooks()
    for webhook in webhooks:
        if webhook.name == name:
            if webhook.token is None:
                await webhook.delete()
            else:
                return webhook

    return await channel.create_webhook(name=name)


async def move_message_via_webhook(
    webhook: discord.Webhook,
    message: discord.Message,
    executor: discord.Member | None = None,
    *,
    thread: discord.abc.Snowflake = discord.utils.MISSING,
    thread_name: str = discord.utils.MISSING,
) -> discord.WebhookMessage:
    msg_data = await scrape_message_data(message)
    msg = await webhook.send(
        content=msg_data.content + _format_subtext(executor, msg_data),
        poll=message.poll or discord.utils.MISSING,
        username=message.author.display_name,
        avatar_url=message.author.display_avatar.url,
        allowed_mentions=discord.AllowedMentions.none(),
        files=msg_data.attachments,
        thread=thread,
        thread_name=thread_name,
        wait=True,
    )
    await message.delete()
    return msg


def is_dm(account: Account) -> TypeIs[discord.User]:
    return not isinstance(account, discord.Member)


def is_mod(member: discord.Member) -> bool:
    return member.get_role(config.MOD_ROLE_ID) is not None


def is_helper(member: discord.Member) -> bool:
    return member.get_role(config.HELPER_ROLE_ID) is not None


async def try_dm(account: Account, content: str) -> None:
    if account.bot:
        return
    try:
        await account.send(content)
    except discord.Forbidden:
        print(f"Failed to DM {account} with: {shorten(content, width=50)}")


async def _get_original_message(message: discord.Message) -> discord.Message | None:
    if (msg_ref := message.reference) is None:
        return None
    if msg_ref.cached_message is not None:
        return msg_ref.cached_message
    if (
        message.guild is None
        or msg_ref.channel_id is None
        or msg_ref.message_id is None
    ):
        return None
    if not isinstance(
        channel := message.guild.get_channel(msg_ref.channel_id), discord.TextChannel
    ):
        return None
    return await channel.fetch_message(msg_ref.message_id)


async def check_message(
    msg: discord.Message, predicate: Callable[[discord.Message], object]
) -> bool:
    """
    Checks a message and its reference chain for a predicate.
    Basically adds support for the forwarding feature.
    """
    if predicate(msg):
        return True
    if (original_msg := await _get_original_message(msg)) is None:
        return False
    return await check_message(original_msg, predicate)
