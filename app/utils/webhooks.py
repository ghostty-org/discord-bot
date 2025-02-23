import re
from collections.abc import Callable
from io import BytesIO

import discord
import httpx

from app.setup import bot
from app.utils.message_data import MessageData, scrape_message_data

GuildTextChannel = discord.TextChannel | discord.Thread

_EMOJI_REGEX = re.compile(r"<(a?):(\w+):(\d+)>", re.ASCII)


def _convert_nitro_emojis(s: str, *, force: bool = False) -> str:
    """
    Converts a custom emoji to a concealed hyperlink.  Set `force` to True
    to convert emojis in the current guild too.
    """
    guild = next(g for g in bot.guilds if "ghostty" in g.name.casefold())

    def r(match: re.Match) -> str:
        animated = bool(match.group(1))
        id_ = int(match.group(3))
        emoji = bot.get_emoji(id_)
        if not force and not animated and emoji and emoji.guild_id == guild.id:
            return match.group(0)

        ext = "gif" if animated else "webp"
        tag = "&animated=true" * animated
        name = match.group(2)
        return f"[{name}](https://cdn.discordapp.com/emojis/{id_}.{ext}?size=48{tag}&name={name})"

    return _EMOJI_REGEX.sub(r, s)


async def _get_sticker_embed(sticker: discord.Sticker) -> discord.Embed:
    # Lottie images can't be used in embeds, unfortunately.
    if sticker.format == discord.StickerFormatType.lottie:
        embed = discord.Embed()
        embed.set_footer(text="Unable to attach sticker.")
        embed.color = discord.Color.brand_red()
        return embed

    async with httpx.AsyncClient() as client:
        for u in [
            sticker.url,
            # Discord sometimes returns the wrong CDN link.
            sticker.url.replace("cdn.discordapp.com", "media.discordapp.net"),
            # Same as above but backward, just in case.
            sticker.url.replace("media.discordapp.net", "cdn.discordapp.com"),
        ]:
            if (await client.head(u)).is_success:
                embed = discord.Embed().set_image(url=u)
                if sticker.format == discord.StickerFormatType.apng:
                    embed.set_footer(text="Unable to animate sticker.")
                    embed.color = discord.Color.orange()
                return embed

    embed = discord.Embed()
    embed.set_footer(text="Unable to attach sticker.")
    embed.color = discord.Color.brand_red()
    return embed


def _format_subtext(executor: discord.Member | None, msg_data: MessageData) -> str:
    lines: list[str] = []
    if reactions := msg_data.reactions.items():
        lines.append("   ".join(f"{emoji} x{count}" for emoji, count in reactions))
    if executor:
        assert isinstance(msg_data.channel, GuildTextChannel)
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

    subtext = _format_subtext(executor, msg_data)
    content, file = format_or_file(
        msg_data.content,
        template=f"{{}}{subtext}",
        transform=_convert_nitro_emojis,
    )
    if file:
        msg_data.attachments.append(file)
        content += "\n-# (content attached)"

    msg = await webhook.send(
        content=content,
        poll=message.poll or discord.utils.MISSING,
        username=message.author.display_name,
        avatar_url=message.author.display_avatar.url,
        allowed_mentions=discord.AllowedMentions.none(),
        files=msg_data.attachments,
        embeds=message.embeds + [await _get_sticker_embed(s) for s in message.stickers],
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
