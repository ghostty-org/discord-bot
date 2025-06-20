from __future__ import annotations

import asyncio
import datetime as dt
import re
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord
import httpx

from app.setup import bot
from app.utils.message_data import MessageData

if TYPE_CHECKING:
    from collections.abc import Callable

GuildTextChannel = discord.TextChannel | discord.Thread

_EMOJI_REGEX = re.compile(r"<(a?):(\w+):(\d+)>", re.ASCII)

_SNOWFLAKE_REGEX = re.compile(r"<(\D{0,2})(\d+)>", re.ASCII)

# A list of image formats supported by Discord, in the form of their file
# extension (including the leading dot).
SUPPORTED_IMAGE_FORMATS = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})

# Non-system-message types taken from the description of
# https://discordpy.readthedocs.io/en/stable/api.html#discord.Message.system_content.
# However, also include bot commands, despite them being system messages.
NON_SYSTEM_MESSAGE_TYPES = frozenset({
    discord.MessageType.default,
    discord.MessageType.reply,
    discord.MessageType.chat_input_command,
    discord.MessageType.context_menu_command,
})


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
    if message.reference.type is not discord.MessageReferenceType.forward:
        # We don't have a forward, fantastic, we're done here.
        return ref
    # And now, we have a forward. Discord doesn't collapse forwarded forwards,
    # so we shall do it ourselves. This loop should not run for replies, as if
    # that happens we would end up dereferencing all the way back to the start
    # of a reply chain, which would be a horrendous idea.
    message = ref
    while (ref := await _get_original_message(message)) is not None:
        if ref is discord.utils.MISSING:
            # We don't have the forward, but there *should* have been one; this
            # isn't included in the check above with `is not None` because
            # otherwise it would return an empty message in the middle of the
            # forward chain, rather than being converted into an error embed.
            return discord.utils.MISSING
        assert message.reference is not None
        if message.reference.type is not discord.MessageReferenceType.forward:
            # This check is subtly different from the one at the top. If we
            # have a reference that's not a forward, we don't want to continue,
            # of course. *But*, unlike up top where we return the reference, we
            # want to return the current message itself, as otherwise we would
            # be returning the reply the last forward is replying to rather than
            # the last forward itself.
            return message
        message = ref
    return message


def _unattachable_embed(unattachable_elem: str, **kwargs: Any) -> discord.Embed:
    """kwargs are passed to discord.Embed()."""
    kwargs["color"] = discord.Color.brand_red()
    return discord.Embed(**kwargs).set_footer(
        text=f"Unable to attach {unattachable_elem}."
    )


def _convert_nitro_emojis(content: str, *, force: bool = False) -> str:
    """
    Convert custom emojis to concealed hyperlinks.  Set `force` to True to
    convert emojis in the current guild too.
    """
    guild = get_ghostty_guild()

    def replace_nitro_emoji(match: re.Match[str]) -> str:
        animated, name, id_ = match.groups()
        emoji = bot.get_emoji(int(id_))
        if not force and emoji and emoji.guild_id == guild.id:
            return match[0]

        ext = "gif" if animated else "webp"
        tag = animated and "&animated=true"
        return f"[{name}](<https://cdn.discordapp.com/emojis/{id_}.{ext}?size=48{tag}&name={name}>)"

    return _EMOJI_REGEX.sub(replace_nitro_emoji, content)


async def _get_sticker_embed(sticker: discord.StickerItem) -> discord.Embed:
    description = (await sticker.fetch()).description
    if sticker.format is discord.StickerFormatType.lottie:
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
            embed = discord.Embed(title=sticker.name).set_image(url=u)
            footer = description
            if sticker.format is discord.StickerFormatType.apng:
                footer = "Unable to animate sticker" + (
                    f" • {footer}" if footer else "."
                )
                embed.color = discord.Color.orange()
            embed.set_footer(text=footer)
            return embed
    return _unattachable_embed("sticker", title=sticker.name, description=description)


def truncate(s: str, length: int, *, suffix: str = "…") -> str:
    if len(s) <= length:
        return s
    return s[: length - len(suffix)] + suffix


async def _format_reply(reply: discord.Message) -> discord.Embed:
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
    return (
        discord.Embed(description=f"{description_prefix}{truncate(description, 100)}")
        .set_author(
            name=f"↪️ Replying to {reply.author.display_name}",
            icon_url=reply.author.display_avatar,
        )
        .add_field(name="", value=f"-# [**Jump**](<{reply.jump_url}>) 📎")
    )


async def _format_context_menu_command(reply: discord.Message) -> discord.Embed:
    return (await _format_reply(reply)).set_author(
        name=f"⚡ Acting on {reply.author.display_name}'s message",
        icon_url=reply.author.display_avatar,
    )


async def _format_forward(
    forward: discord.Message,
) -> tuple[list[discord.Embed], list[discord.File]]:
    if forward is discord.utils.MISSING:
        return [_unattachable_embed("forward")], []

    content = _convert_nitro_emojis(forward.content)
    if len(content) > 4096:
        content = forward.content

    msg_data = await MessageData.scrape(forward)
    embeds = [
        *(e for e in forward.embeds if not e.url),
        *await asyncio.gather(*map(_get_sticker_embed, forward.stickers)),
    ]
    embed = discord.Embed(description=content, timestamp=forward.created_at)
    embed.set_author(name="➜ Forwarded")

    if hasattr(forward.channel, "name"):
        # Some channel types don't have a `name` and Pyright can't figure out
        # that we certainly have a `name` here.
        assert not isinstance(
            forward.channel, discord.DMChannel | discord.PartialMessageable
        )
        embed.set_footer(text=f"#{forward.channel.name}")

    images = [
        file
        for file in msg_data.files
        if Path(file.filename).suffix in SUPPORTED_IMAGE_FORMATS
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
    if embeds or len(msg_data.files) > (1 if images else 0):
        embed.add_field(
            name="", value="-# (other forwarded content is attached)", inline=False
        )

    if msg_data.skipped_attachments:
        skipped = _SubText.format_skipped(msg_data.skipped_attachments)
        embed.add_field(name="", value=f"-# {skipped}", inline=False)

    embed.add_field(
        name="", value=f"-# [**Jump**](<{forward.jump_url}>) 📎", inline=False
    )

    embeds.insert(0, embed)
    return embeds, msg_data.files


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
            "⚡ Message"
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
        prefix = "/" * (message.type is not discord.MessageType.context_menu_command)
        name = f"`{prefix}{interaction.name}`"
    else:
        name = "a command"
    user = message.interaction_metadata.user
    return f"-# *{user.mention} used {name}*\n{message.content}"


def dynamic_timestamp(dt: dt.datetime, fmt: str | None = None) -> str:
    fmt = f":{fmt}" if fmt is not None else ""
    return f"<t:{int(dt.timestamp())}{fmt}>"


class _SubText:
    # NOTE: when changing the subtext's format in ways that are not
    # backward-compatible, don't forget to bump the cut-off time in
    # app/components/message_filter.py!
    reactions: str
    timestamp: str
    author: str
    move_hint: str
    skipped: str
    poll_error: str

    def __init__(
        self,
        msg_data: MessageData,
        executor: discord.Member | None,
        poll: discord.Poll | None = None,
    ) -> None:
        self.msg_data = msg_data
        self._format_reactions()
        self._format_timestamp()
        self.author = f"Authored by {msg_data.author.mention}"
        assert isinstance(self.msg_data.channel, GuildTextChannel)
        self.move_hint = (
            f"Moved from {self.msg_data.channel.mention} by {executor.mention}"
            if executor is not None
            else ""
        )
        self.skipped = (
            self.format_skipped(skipped)
            if (skipped := msg_data.skipped_attachments)
            else ""
        )
        self.poll_error = (
            "Unable to attach closed poll" if poll is discord.utils.MISSING else ""
        )

    def _format_reactions(self) -> None:
        formatted_reactions = [
            f"{emoji} ×{reaction.count}"  # noqa: RUF001
            if isinstance(emoji := reaction.emoji, str)
            or getattr(emoji, "is_usable", lambda: False)()
            else f"[{emoji.name}](<{emoji.url}>) ×{reaction.count}"  # noqa: RUF001
            for reaction in self.msg_data.reactions
        ]
        self.reactions = "   ".join(formatted_reactions)

    def _format_timestamp(self) -> None:
        if self.msg_data.created_at > dt.datetime.now(tz=dt.UTC) - dt.timedelta(
            hours=12
        ):
            self.timestamp = ""
            return
        self.timestamp = dynamic_timestamp(self.msg_data.created_at)
        if self.msg_data.edited_at is not None:
            self.timestamp += (
                f" (edited at {dynamic_timestamp(self.msg_data.edited_at, 't')})"
            )

    @staticmethod
    def format_skipped(skipped: int) -> str:
        return f"Skipped {skipped} large attachment{'s' * (skipped != 1)}"

    def format(self) -> str:
        original_message_info = (
            self.author,
            " on " if self.author and self.timestamp else "",
            self.timestamp,
        )
        context = (
            "".join(original_message_info),
            self.move_hint,
            self.skipped,
            self.poll_error,
        )
        return self._sub_join(self.reactions, " • ".join(filter(None, context)))

    def format_simple(self) -> str:
        return self._sub_join(self.reactions, self.skipped, self.poll_error)

    @staticmethod
    def _sub_join(*strs: str) -> str:
        return "\n".join(f"-# {s}" for s in strs if s)


async def get_or_create_webhook(
    channel: discord.TextChannel | discord.ForumChannel, name: str = "Ghostty Moderator"
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


async def move_message_via_webhook(  # noqa: PLR0913
    webhook: discord.Webhook,
    message: discord.Message,
    executor: discord.Member | None = None,
    *,
    thread: discord.abc.Snowflake = discord.utils.MISSING,
    thread_name: str = discord.utils.MISSING,
    include_move_marks: bool = True,
) -> discord.WebhookMessage:
    """
    WARNING: it is the caller's responsibility to check message_can_be_moved()
    and to display an informative warning message.
    """
    assert message_can_be_moved(message)

    msg_data = await MessageData.scrape(message)

    embeds = [
        *(e for e in message.embeds if not e.url),
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
                msg_data.files.extend(forward_attachments)
            elif message.type is discord.MessageType.context_menu_command:
                embeds.append(await _format_context_menu_command(ref))
            else:
                embeds.append(await _format_reply(ref))

    if (
        message.poll is None
        # Discord does not like polls with a negative duration. Polls created
        # by a webhook cannot be ended manually, so simply discard polls which
        # have ended.
        or message.poll.expires_at is None
        or dt.datetime.now(tz=dt.UTC) >= message.poll.expires_at
    ):
        poll = discord.utils.MISSING
    else:
        poll = message.poll

    # The if expression is to skip the poll ended message if there was no poll.
    s = _SubText(msg_data, executor, poll if message.poll is not None else None)
    subtext = s.format() if include_move_marks else s.format_simple()
    content, file = format_or_file(
        _format_interaction(message),
        template=f"{{}}\n{subtext}",
        transform=_convert_nitro_emojis,
    )
    if file:
        msg_data.files.append(file)
        content += " • Content attached" if content.strip() else "-# Content attached"

    msg = await webhook.send(
        content=content,
        poll=poll,
        username=message.author.display_name,
        avatar_url=message.author.display_avatar.url,
        allowed_mentions=discord.AllowedMentions.none(),
        files=msg_data.files,
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


class MovedMessageLookupFailed(Enum):
    NOT_FOUND = -1
    NOT_MOVED = -2


async def get_moved_message(
    message: discord.Message, *, webhook_name: str = "Ghostty Moderator"
) -> discord.WebhookMessage | MovedMessageLookupFailed:
    if message.webhook_id is None or isinstance(
        message.channel,
        # These types can't even have a webhook.
        discord.DMChannel | discord.GroupChannel | discord.PartialMessageable,
    ):
        return MovedMessageLookupFailed.NOT_MOVED

    if isinstance(message.channel, discord.Thread):
        thread = message.channel
        if (channel := thread.parent) is None:
            return MovedMessageLookupFailed.NOT_FOUND
    else:
        channel = message.channel
        thread = discord.utils.MISSING

    for webhook in await channel.webhooks():
        if webhook.id == message.webhook_id:
            break
    else:
        return MovedMessageLookupFailed.NOT_MOVED
    if webhook.name != webhook_name:
        # More heuristics to determine if a webhook message is a moved message.
        return MovedMessageLookupFailed.NOT_MOVED

    try:
        return await webhook.fetch_message(message.id, thread=thread)
    except discord.Forbidden:
        return MovedMessageLookupFailed.NOT_FOUND
    except discord.NotFound:
        # NOTE: while it may seem like this should be returning `NotFound`,
        # this branch is run when the *webhook* couldn't find the associated
        # message, rather than when the message doesn't exist. Since all moved
        # messages are sent by the webhook, this branch symbolizes a message
        # that isn't a moved message.
        return MovedMessageLookupFailed.NOT_MOVED


def _find_snowflake(content: str, type_: str) -> tuple[int, int] | tuple[None, None]:
    """
    WARNING: this function does not account for Markdown features such as code
    blocks that may disarm a snowflake.
    """
    # NOTE: while this function could just return tuple[int, int] | None, that
    # makes it less convenient to destructure the return value.
    snowflake = _SNOWFLAKE_REGEX.search(content)
    if snowflake is None or snowflake[1] != type_:
        return None, None
    return int(snowflake[2]), snowflake.span()[0]


def get_moved_message_author_id(message: discord.WebhookMessage) -> int | None:
    # NOTE: this function takes a discord.WebhookMessage instead of
    # a discord.Message to force the caller to ensure that the requested
    # message is actually from a webhook.

    # HACK: as far as I know, Discord does not provide any way to attach
    # a hidden number to a webhook message, nor does it provide a way to link
    # a webhook message to a user. Thus, this information is extracted from the
    # subtext of moved messages.
    try:
        subtext = message.content.splitlines()[-1]
    except IndexError:
        return None
    # Heuristics to determine if a message is really a moved message.
    if not subtext.startswith("-# "):
        return None
    # One other thing that could be checked is whether content.splitlines() is
    # at least two elements long; that would backfire when moved media or
    # forwards is passed through this function, however, as those move messages
    # don't contain anything except the subtext in their `Message.content`.

    # If we have a channel mention, the executor is present; discard that part
    # so that the executor is not accidentally picked as the author.
    _, pos = _find_snowflake(subtext, "#")
    if pos is not None:
        subtext = subtext[:pos]

    snowflake, _ = _find_snowflake(subtext, "@")
    return snowflake
