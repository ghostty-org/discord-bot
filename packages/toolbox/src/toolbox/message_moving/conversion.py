import asyncio
import re
from pathlib import Path
from typing import Any

import discord as dc
import httpx

from .subtext import Subtext
from toolbox.discord import SUPPORTED_IMAGE_FORMATS
from toolbox.messages import get_files
from toolbox.misc import truncate

_EMOJI_REGEX = re.compile(r"<(a?):(\w+):(\d+)>", re.ASCII)


async def _get_original_message(message: dc.Message) -> dc.Message | None:
    """Can throw dc.errors.NotFound if the original message was deleted."""
    if (msg_ref := message.reference) is None:
        return None
    if msg_ref.cached_message is not None:
        return msg_ref.cached_message
    if message.guild is None or msg_ref.message_id is None:
        return None
    channel = message.guild.get_channel(msg_ref.channel_id)
    if not isinstance(channel, dc.TextChannel):
        # There *is* a reference, but we can't access it.
        return dc.utils.MISSING
    return await channel.fetch_message(msg_ref.message_id)


def _unattachable_embed(unattachable_elem: str, **kwargs: Any) -> dc.Embed:
    """kwargs are passed to dc.Embed()."""
    kwargs["color"] = dc.Color.brand_red()
    return dc.Embed(**kwargs).set_footer(text=f"Unable to attach {unattachable_elem}.")


def convert_nitro_emojis(
    client: dc.Client, guild: dc.Guild, content: str, *, force: bool = False
) -> str:
    """
    Convert custom emojis to concealed hyperlinks.  Set `force` to True to convert
    emojis in the current guild too.
    """

    def replace_nitro_emoji(match: re.Match[str]) -> str:
        animated, name, id_ = match.groups()
        emoji = client.get_emoji(int(id_))
        if not force and emoji and emoji.guild_id == guild.id:
            return match[0]

        ext = "gif" if animated else "webp"
        tag = animated and "&animated=true"
        return f"[{name}](<https://cdn.discordapp.com/emojis/{id_}.{ext}?size=48{tag}&name={name}>)"

    return _EMOJI_REGEX.sub(replace_nitro_emoji, content)


async def get_sticker_embed(sticker: dc.StickerItem) -> dc.Embed:
    description = (await sticker.fetch()).description
    if sticker.format is dc.StickerFormatType.lottie:
        # Lottie images can't be used in embeds, unfortunately.
        return _unattachable_embed(
            "sticker", title=sticker.name, description=description
        )
    async with httpx.AsyncClient() as client:
        for u in (
            sticker.url,
            # Discord sometimes returns the wrong CDN link.
            sticker.url.replace("cdn.discordapp.com", "media.discordapp.net"),
            # Same as above but backward, just in case.
            sticker.url.replace("media.discordapp.net", "cdn.discordapp.com"),
        ):
            if not (await client.head(u)).is_success:
                # The sticker URL is not actually available.
                continue
            embed = dc.Embed(title=sticker.name).set_image(url=u)
            footer = description
            if sticker.format is dc.StickerFormatType.apng:
                footer = "Unable to animate sticker" + (
                    f" • {footer}" if footer else "."
                )
                embed.color = dc.Color.orange()
            return embed.set_footer(text=footer)
    return _unattachable_embed("sticker", title=sticker.name, description=description)


def format_reply(reply: dc.Message) -> dc.Embed:
    if reply is dc.utils.MISSING:
        return _unattachable_embed("reply")
    description_prefix = ""
    description = reply.content
    if reply.message_snapshots:
        description_prefix = "➜ Forwarded\n"
        # Only include the first message snapshot.
        if content := reply.message_snapshots[0].content:
            description = f"> {content}"
        else:
            description = "> *Some forwarded content elided.*"
    return (
        dc
        .Embed(description=f"{description_prefix}{truncate(description, 100)}")
        .set_author(
            name=f"↪️ Replying to {reply.author.display_name}",  # test: allow-vs16
            icon_url=reply.author.display_avatar,
        )
        .add_field(name="", value=f"-# [**Jump**](<{reply.jump_url}>) 📎")
    )


def format_context_menu_command(reply: dc.Message) -> dc.Embed:
    return format_reply(reply).set_author(
        name=f"⚡ Acting on {reply.author.display_name}'s message",
        icon_url=reply.author.display_avatar,
    )


async def format_forward(
    client: dc.Client, guild: dc.Guild, forward: dc.MessageSnapshot
) -> tuple[list[dc.Embed], list[dc.File]]:
    content = convert_nitro_emojis(client, guild, forward.content)
    if len(content) > 4096:
        content = forward.content

    files, skipped_attachments = await get_files(forward.attachments)
    embeds = [
        *(e for e in forward.embeds if not e.url),
        *await asyncio.gather(*map(get_sticker_embed, forward.stickers)),
    ]
    embed = dc.Embed(description=content, timestamp=forward.created_at)
    embed.set_author(name="➜ Forwarded")

    images = [
        file for file in files if Path(file.filename).suffix in SUPPORTED_IMAGE_FORMATS
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
            # Try both, as embeds which have not yet been sent to Discord will not have
            # a proxy_url.
            embed.set_image(url=image.proxy_url or image.url)
            embeds.remove(image_only_embeds[0])
    if embeds or len(files) > (1 if images else 0):
        embed.add_field(
            name="", value="-# (other forwarded content is attached)", inline=False
        )

    if skipped_attachments:
        skipped = Subtext.format_skipped(skipped_attachments)
        embed.add_field(name="", value=f"-# {skipped}", inline=False)

    if (message := forward.cached_message) is not None:
        if not isinstance(message.channel, dc.DMChannel | dc.PartialMessageable):
            embed.set_footer(text=f"#{message.channel.name}")
        embed.add_field(
            name="", value=f"-# [**Jump**](<{message.jump_url}>) 📎", inline=False
        )

    embeds.insert(0, embed)
    return embeds, files


def format_missing_reply(message: dc.Message) -> dc.Embed:
    return dc.Embed(description="*Original message was deleted.*").set_author(
        name=(
            "⚡ Message"
            if message.type is dc.MessageType.context_menu_command
            else "↪️ Reply"  # test: allow-vs16
        )
    )


def format_interaction(message: dc.Message) -> str:
    if not message.interaction_metadata:
        return message.content
    # HACK: Message.interaction is deprecated, and discord.py disables any warning
    # filter resulting in a bunch of warnings spammed in the logs even if it is ignored.
    # There is no other way to get the name, and Message._interaction is not marked
    # deprecated. Delectable.
    if hasattr(message, "_interaction") and (interaction := message._interaction):  # pyright: ignore[reportPrivateUsage] # noqa: SLF001
        prefix = "/" * (message.type is not dc.MessageType.context_menu_command)
        name = f"`{prefix}{interaction.name}`"
    else:
        name = "a command"
    user = message.interaction_metadata.user
    return f"-# *{user.mention} used {name}*\n{message.content}"


async def get_reply_embed(message: dc.Message) -> dc.Embed | None:
    try:
        ref = await _get_original_message(message)
    except dc.errors.NotFound:
        return format_missing_reply(message)
    if ref is None:
        return None
    assert message.reference is not None
    if message.reference.type is dc.MessageReferenceType.reply:
        return format_reply(ref)
    if message.type is dc.MessageType.context_menu_command:
        return format_context_menu_command(ref)
    return None
