from __future__ import annotations

import asyncio
import datetime as dt
import re
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import discord
import httpx

from app.setup import bot
from app.utils.message_data import MessageData, scrape_message_data

if TYPE_CHECKING:
    from collections.abc import Callable

GuildTextChannel = discord.TextChannel | discord.Thread

_EMOJI_REGEX = re.compile(r"<(a?):(\w+):(\d+)>", re.ASCII)

# A list of image formats supported by Discord, in the form of their file
# extension (including the leading dot).
SUPPORTED_IMAGE_FORMATS = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})

# Non-system-message types taken from the description of
# https://discordpy.readthedocs.io/en/stable/api.html#discord.Message.system_content.
# However, also include bot commands, despite them being system messages.
NON_SYSTEM_MESSAGE_TYPES = frozenset(
    {
        discord.MessageType.default,
        discord.MessageType.reply,
        discord.MessageType.chat_input_command,
        discord.MessageType.context_menu_command,
    }
)


def get_ghostty_guild() -> discord.Guild:
    try:
        return next(g for g in bot.guilds if "ghostty" in g.name.casefold())
    except StopIteration:
        msg = "bot guild name does not contain 'ghostty'"
        raise ValueError(msg) from None


async def _get_original_message(message: discord.Message) -> discord.Message | None:
    """Can throw discord.errors.NotFound if the original message was deleted."""
    if (msg_ref := message.reference) is None:
        return None
    if msg_ref.cached_message is not None:
        return msg_ref.cached_message
    if message.guild is None or msg_ref.message_id is None:
        return None
    channel = message.guild.get_channel(msg_ref.channel_id)
    if not isinstance(channel, discord.TextChannel):
        # There *is* a reference, but we can't access it.
        return discord.utils.MISSING
    return await channel.fetch_message(msg_ref.message_id)


async def _get_reference(message: discord.Message) -> discord.Message | None:
    ref = await _get_original_message(message)
    if ref is None or ref is discord.utils.MISSING:
        # There was no reference whatsoever.
        return ref
    assert message.reference is not None
    if message.reference.type != discord.MessageReferenceType.forward:
        # We don't have a forward, fantastic, we're done here.
        return ref
    # And now, we have a forward. Discord doesn't collapse forwarded forwards,
    # so we shall do it ourselves. This loop should not run for replies, as if
    # that happens we would end up dereferencing all the way back to the start
    # of a reply chain, which would be a horendous idea.
    message = ref
    while (ref := await _get_original_message(message)) is not None:
        if ref is discord.utils.MISSING:
            # We don't have the forward, but there *should* have been one; this
            # isn't included in the check above with `is not None` because
            # otherwise it would return an empty message in the middle of the
            # forward chain, rather than being converted into an error embed.
            return discord.utils.MISSING
        assert message.reference is not None
        if message.reference.type != discord.MessageReferenceType.forward:
            # This check is subtly different from the one at the top. If we
            # have a reference that's not a forward, we don't want to continue,
            # of course. *But*, unlike up top where we return the reference, we
            # want to return the current message itself, as otherwise we would
            # be returning the reply the last forward is replying to rather than
            # the last forward itself.
            return message
        message = ref
        ref = await _get_original_message(message)
    return message


def _unattachable_embed(unattachable_elem: str) -> discord.Embed:
    return discord.Embed(color=discord.Color.brand_red()).set_footer(
        text=f"Unable to attach {unattachable_elem}."
    )


def _convert_nitro_emojis(content: str, *, force: bool = False) -> str:
    """
    Converts a custom emoji to a concealed hyperlink.  Set `force` to True
    to convert emojis in the current guild too.
    """
    guild = get_ghostty_guild()

    def replace_nitro_emoji(match: re.Match[str]) -> str:
        animated, name, id_ = match.groups()
        emoji = bot.get_emoji(int(id_))
        if not force and not animated and emoji and emoji.guild_id == guild.id:
            return match[0]

        ext = "gif" if animated else "webp"
        tag = animated and "&animated=true"
        return f"[{name}](https://cdn.discordapp.com/emojis/{id_}.{ext}?size=48{tag}&name={name})"

    return _EMOJI_REGEX.sub(replace_nitro_emoji, content)


async def _get_sticker_embed(sticker: discord.StickerItem) -> discord.Embed:
    # Lottie images can't be used in embeds, unfortunately.
    if sticker.format is discord.StickerFormatType.lottie:
        return _unattachable_embed("sticker")
    async with httpx.AsyncClient() as client:
        for u in (
            sticker.url,
            # Discord sometimes returns the wrong CDN link.
            sticker.url.replace("cdn.discordapp.com", "media.discordapp.net"),
            # Same as above but backward, just in case.
            sticker.url.replace("media.discordapp.net", "cdn.discordapp.com"),
        ):
            if (await client.head(u)).is_success:
                embed = discord.Embed().set_image(url=u)
                if sticker.format is discord.StickerFormatType.apng:
                    embed.set_footer(text="Unable to animate sticker.")
                    embed.color = discord.Color.orange()
                return embed
    return _unattachable_embed("sticker")


def truncate(s: str, length: int, *, suffix: str = "…") -> str:
    if len(s) <= length:
        return s
    return s[: length - len(suffix)] + suffix


async def _format_reply(
    reply: discord.Message, message_map: dict[int, str] | None = None
) -> discord.Embed:
    if reply is discord.utils.MISSING:
        return _unattachable_embed("reply")

    description_prefix = ""
    description = reply.content
    ref_exists = True
    try:
        ref = await _get_reference(reply)
    except discord.errors.NotFound:
        ref = discord.utils.MISSING
        ref_exists = False
    if ref is not None:
        assert reply.reference is not None
        if reply.reference.type is discord.MessageReferenceType.forward:
            description_prefix = "➜ Forwarded\n"
            if not ref_exists:
                description = "> *Forwarded message was deleted.*"
            elif ref is discord.utils.MISSING:
                description = "> *Unable to attach forward.*"
            elif ref.content:
                description = f"> {ref.content}"
            else:
                description = "> *Some forwarded content elided.*"

    link = (
        reply.jump_url
        if message_map is None
        else message_map.get(reply.id, reply.jump_url)
    )
    return (
        discord.Embed(description=f"{description_prefix}{truncate(description, 100)}")
        .set_author(
            name=f"↪️ Replying to {reply.author.display_name}",
            icon_url=reply.author.display_avatar,
        )
        .add_field(name="", value=f"-# [**Jump**](<{link}>) 📎")
    )


async def _format_context_menu_command(
    reply: discord.Message, message_map: dict[int, str] | None = None
) -> discord.Embed:
    return (await _format_reply(reply, message_map)).set_author(
        name=f"⚡️ Acting on {reply.author.display_name}'s message",
        icon_url=reply.author.display_avatar,
    )


async def _format_forward(
    forward: discord.Message, message_map: dict[int, str] | None = None
) -> tuple[list[discord.Embed], list[discord.File]]:
    if forward is discord.utils.MISSING:
        return [_unattachable_embed("forward")], []

    msg_data = await scrape_message_data(forward)
    embeds = [
        *forward.embeds,
        *await asyncio.gather(*map(_get_sticker_embed, forward.stickers)),
    ]

    link = (
        forward.jump_url
        if message_map is None
        else message_map.get(forward.id, forward.jump_url)
    )
    embed = discord.Embed(
        description=forward.content, timestamp=forward.created_at, url=link
    ).set_author(name="➜ Forwarded")

    if hasattr(forward.channel, "name"):
        # Some channel types don't have a `name` and Pyright can't figure out
        # that we certainly have a `name` here.
        assert not isinstance(
            forward.channel, discord.DMChannel | discord.PartialMessageable
        )
        embed.set_footer(text=f"#{forward.channel.name}")

    images = [
        attachment
        for attachment in msg_data.attachments
        if Path(attachment.filename).suffix in SUPPORTED_IMAGE_FORMATS
    ]
    image_only_embeds = [
        embed
        for embed in embeds
        if embed.image and not (embed.title or embed.description or embed.fields)
    ]
    if len(images) == 1 or len(image_only_embeds) == 1:
        if images:
            # https://discordpy.readthedocs.io/en/stable/faq.html#how-do-i-use-a-local-image-file-for-an-embed-image
            embed.set_image(url="attachment://" + images[0].filename)
        else:
            image = image_only_embeds[0].image
            # Try both, as embeds which have not yet been sent to Discord will
            # not have a proxy_url.
            embed.set_image(url=image.proxy_url or image.url)
            embeds.remove(image_only_embeds[0])
    if embeds or len(msg_data.attachments) > (1 if images else 0):
        embed.add_field(
            name="", value="-# (other forwarded content is attached)", inline=False
        )

    for line in _format_subtext(
        None,
        msg_data,
        include_timestamp=False,
        # Get rid of the leading newline.
    ).splitlines()[1:]:
        embed.add_field(name="", value=line, inline=False)
    embed.add_field(name="", value=f"-# [**Jump**](<{link}>) 📎", inline=False)

    embeds.insert(0, embed)
    return embeds, msg_data.attachments


def _format_missing_reference(
    message: discord.Message,
) -> discord.Embed:
    assert message.reference is not None
    if message.reference.type is discord.MessageReferenceType.forward:
        return discord.Embed(description="*Forwarded message was deleted.*").set_author(
            name="➜ Forwarded"
        )
    return discord.Embed(description="*Original message was deleted.*").set_author(
        name=(
            "⚡️ Message"
            if message.type is discord.MessageType.context_menu_command
            else "↪️ Reply"
        )
    )


def _format_interaction(message: discord.Message) -> str:
    if not message.interaction_metadata:
        return message.content
    # HACK: Message.interaction is deprecated, and discord.py disables any
    # warning filter resulting in a bunch of warnings spammed in the logs even
    # if it is ignored. There is no other way to get the name, and
    # Message._interaction is not marked deprecated. Delectable.
    if hasattr(message, "_interaction") and (interaction := message._interaction):  # pyright: ignore [reportPrivateUsage] # noqa: SLF001
        prefix = "/" * (message.type != discord.MessageType.context_menu_command)
        name = f"`{prefix}{interaction.name}`"
    else:
        name = "a command"
    user = message.interaction_metadata.user
    return f"-# *{user.mention} used {name}*\n{message.content}"


def dynamic_timestamp(dt: dt.datetime, fmt: str | None = None) -> str:
    fmt = f":{fmt}" if fmt is not None else ""
    return f"<t:{int(dt.timestamp())}{fmt}>"


def _format_subtext(
    executor: discord.Member | None,
    msg_data: MessageData,
    *,
    include_timestamp: bool = True,
) -> str:
    lines: list[str] = []
    if reactions := msg_data.reactions.items():
        lines.append("   ".join(f"{emoji} x{count}" for emoji, count in reactions))
    if msg_data.created_at > dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=12):
        include_timestamp = False
    if include_timestamp:
        line = dynamic_timestamp(msg_data.created_at)
        if msg_data.edited_at is not None:
            line += f" (edited at {dynamic_timestamp(msg_data.edited_at, 't')})"
        lines.append(line)
    if executor:
        assert isinstance(msg_data.channel, GuildTextChannel)
        line = f"Moved from {msg_data.channel.mention} by {executor.mention}"
        if include_timestamp:
            lines[-1] += " • " + line
        else:
            lines.append(line)
    if skipped := msg_data.skipped_attachments:
        lines.append(f"(skipped {skipped} large attachment{'s' * (skipped != 1)})")
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


def message_can_be_moved(message: discord.Message) -> bool:
    return message.type in NON_SYSTEM_MESSAGE_TYPES


async def move_message_via_webhook(
    webhook: discord.Webhook,
    message: discord.Message,
    executor: discord.Member | None = None,
    *,
    thread: discord.abc.Snowflake = discord.utils.MISSING,
    thread_name: str = discord.utils.MISSING,
) -> discord.WebhookMessage:
    """
    WARNING: it is the caller's responsibility to check message_can_be_moved()
    and to display an informative warning message.
    """
    assert message_can_be_moved(message)

    msg_data = await scrape_message_data(message)

    embeds = [
        *message.embeds,
        *await asyncio.gather(*map(_get_sticker_embed, message.stickers)),
    ]

    try:
        ref = await _get_reference(message)
    except discord.errors.NotFound:
        embeds.append(_format_missing_reference(message))
    else:
        if ref is not None:
            assert message.reference is not None
            if message.reference.type is discord.MessageReferenceType.forward:
                forward_embeds, forward_attachments = await _format_forward(ref)
                embeds = [*forward_embeds, *embeds]
                msg_data.attachments.extend(forward_attachments)
            elif message.type is discord.MessageType.context_menu_command:
                embeds.append(await _format_context_menu_command(ref))
            else:
                embeds.append(await _format_reply(ref))

    subtext = _format_subtext(executor, msg_data)
    content, file = format_or_file(
        _format_interaction(message),
        template=f"{{}}{subtext}",
        transform=_convert_nitro_emojis,
    )
    if file:
        msg_data.attachments.append(file)
        content += "\n-# (content attached)"

    # Discord does not like negative poll durations. Polls created by a Webhook
    # cannot be ended manually, so simply discard polls which have ended.
    if message.poll is None:
        poll = discord.utils.MISSING
    elif (
        message.poll.expires_at is None
        or dt.datetime.now(tz=dt.UTC) >= message.poll.expires_at
    ):
        content += "\n-# (unable to attach closed poll)"
        poll = discord.utils.MISSING
    else:
        poll = message.poll

    msg = await webhook.send(
        content=content,
        poll=poll,
        username=message.author.display_name,
        avatar_url=message.author.display_avatar.url,
        allowed_mentions=discord.AllowedMentions.none(),
        files=msg_data.attachments,
        embeds=embeds,
        thread=thread,
        thread_name=thread_name,
        wait=True,
    )
    await message.delete()
    return msg


def format_or_file(
    message: str,
    *,
    template: str | None = None,
    transform: Callable[[str], str] | None = None,
) -> tuple[str, discord.File | None]:
    if template is None:
        template = "{}"

    full_message = template.format(message)
    if transform is not None:
        full_message = transform(full_message)

    if len(full_message) > 2000:
        return template.format(""), discord.File(
            BytesIO(message.encode()), filename="content.md"
        )
    return full_message, None
