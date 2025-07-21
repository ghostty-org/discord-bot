from __future__ import annotations

import asyncio
import datetime as dt
import re
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, overload

import discord as dc
import httpx

from app.setup import bot
from app.utils import GuildTextChannel, dynamic_timestamp, truncate
from app.utils.message_data import ExtensibleMessage, MessageData, get_files

if TYPE_CHECKING:
    from collections.abc import Callable

_EMOJI_REGEX = re.compile(r"<(a?):(\w+):(\d+)>", re.ASCII)
_REACTION_REGEX = re.compile(r"([^\s×]+) ×(\d+)", re.ASCII)  # noqa: RUF001
_SNOWFLAKE_REGEX = re.compile(r"<(\D{0,2})(\d+)>", re.ASCII)

# A list of image formats supported by Discord, in the form of their file extension
# (including the leading dot).
SUPPORTED_IMAGE_FORMATS = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})

# Non-system-message types taken from the description of
# https://discordpy.readthedocs.io/en/stable/api.html#discord.Message.system_content.
# However, also include bot commands, despite them being system messages.
NON_SYSTEM_MESSAGE_TYPES = frozenset({
    dc.MessageType.default,
    dc.MessageType.reply,
    dc.MessageType.chat_input_command,
    dc.MessageType.context_menu_command,
})


def get_ghostty_guild() -> dc.Guild:
    try:
        return next(g for g in bot.guilds if "ghostty" in g.name.casefold())
    except StopIteration:
        msg = "bot guild name does not contain 'ghostty'"
        raise ValueError(msg) from None


async def _get_original_message(message: dc.Message) -> dc.Message | None:
    """Can throw discord.errors.NotFound if the original message was deleted."""
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
    """kwargs are passed to discord.Embed()."""
    kwargs["color"] = dc.Color.brand_red()
    return dc.Embed(**kwargs).set_footer(text=f"Unable to attach {unattachable_elem}.")


def convert_nitro_emojis(content: str, *, force: bool = False) -> str:
    """
    Convert custom emojis to concealed hyperlinks.  Set `force` to True to convert
    emojis in the current guild too.
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


async def _get_sticker_embed(sticker: dc.StickerItem) -> dc.Embed:
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
            embed.set_footer(text=footer)
            return embed
    return _unattachable_embed("sticker", title=sticker.name, description=description)


def _format_reply(reply: dc.Message) -> dc.Embed:
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
        dc.Embed(description=f"{description_prefix}{truncate(description, 100)}")
        .set_author(
            name=f"↪️ Replying to {reply.author.display_name}",  # test: allow-vs16
            icon_url=reply.author.display_avatar,
        )
        .add_field(name="", value=f"-# [**Jump**](<{reply.jump_url}>) 📎")
    )


async def _format_context_menu_command(reply: dc.Message) -> dc.Embed:
    return _format_reply(reply).set_author(
        name=f"⚡ Acting on {reply.author.display_name}'s message",
        icon_url=reply.author.display_avatar,
    )


async def _format_forward(
    forward: dc.MessageSnapshot,
) -> tuple[list[dc.Embed], list[dc.File]]:
    content = convert_nitro_emojis(forward.content)
    if len(content) > 4096:
        content = forward.content

    files, skipped_attachments = await get_files(forward.attachments)
    embeds = [
        *(e for e in forward.embeds if not e.url),
        *await asyncio.gather(*map(_get_sticker_embed, forward.stickers)),
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
        skipped = _Subtext.format_skipped(skipped_attachments)
        embed.add_field(name="", value=f"-# {skipped}", inline=False)

    if (message := forward.cached_message) is not None:
        if not isinstance(message.channel, dc.DMChannel | dc.PartialMessageable):
            embed.set_footer(text=f"#{message.channel.name}")
        embed.add_field(
            name="", value=f"-# [**Jump**](<{message.jump_url}>) 📎", inline=False
        )

    embeds.insert(0, embed)
    return embeds, files


def _format_missing_reply(message: dc.Message) -> dc.Embed:
    return dc.Embed(description="*Original message was deleted.*").set_author(
        name=(
            "⚡ Message"
            if message.type is dc.MessageType.context_menu_command
            else "↪️ Reply"  # test: allow-vs16
        )
    )


def _format_interaction(message: dc.Message) -> str:
    if not message.interaction_metadata:
        return message.content
    # HACK: Message.interaction is deprecated, and discord.py disables any warning
    # filter resulting in a bunch of warnings spammed in the logs even if it is ignored.
    # There is no other way to get the name, and Message._interaction is not marked
    # deprecated. Delectable.
    if hasattr(message, "_interaction") and (interaction := message._interaction):  # pyright: ignore [reportPrivateUsage] # noqa: SLF001
        prefix = "/" * (message.type is not dc.MessageType.context_menu_command)
        name = f"`{prefix}{interaction.name}`"
    else:
        name = "a command"
    user = message.interaction_metadata.user
    return f"-# *{user.mention} used {name}*\n{message.content}"


async def _get_reply_embed(message: dc.Message) -> dc.Embed | None:
    try:
        ref = await _get_original_message(message)
    except dc.errors.NotFound:
        return _format_missing_reply(message)
    if ref is None:
        return None
    assert message.reference is not None
    if message.reference.type is dc.MessageReferenceType.reply:
        return _format_reply(ref)
    if message.type is dc.MessageType.context_menu_command:
        return await _format_context_menu_command(ref)
    return None


def _format_emoji(emoji: str | dc.PartialEmoji | dc.Emoji) -> str:
    if (
        isinstance(emoji, str)
        or (isinstance(emoji, dc.PartialEmoji) and emoji.is_unicode_emoji())
        or (isinstance(emoji, dc.Emoji) and emoji.is_usable())
    ):
        return str(emoji)
    return f"[{emoji.name}](<{emoji.url}>)"


class _Subtext:
    # NOTE: when changing the subtext's format in ways that are not backward-compatible,
    # don't forget to bump the cut-off time in app/components/message_filter.py!
    reactions: str
    timestamp: str
    author: str
    move_hint: str
    skipped: str
    poll_error: str

    def __init__(
        self,
        msg_data: MessageData,
        executor: dc.Member | None,
        poll: dc.Poll | None = None,
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
            "Unable to attach closed poll" if poll is dc.utils.MISSING else ""
        )

    def _format_reactions(self) -> None:
        self.reactions = "   ".join(
            f"{_format_emoji(reaction.emoji)} ×{reaction.count}"  # noqa: RUF001
            for reaction in self.msg_data.reactions
        )

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
            self.skipped,
            self.poll_error,
            self.move_hint,
        )
        return self._sub_join(self.reactions, " • ".join(filter(None, context)))

    def format_simple(self) -> str:
        return self._sub_join(self.reactions, self.skipped, self.poll_error)

    @staticmethod
    def _sub_join(*strs: str) -> str:
        return "\n".join(f"-# {s}" for s in strs if s)


class SplitSubtext:
    def __init__(self, message: MovedMessage) -> None:
        # Since we know that we definitely have a moved message here (due to the
        # restriction on `message`'s type), the last line must be the subtext.
        *lines, self._subtext = message.content.splitlines()
        if not lines:
            self.content, self.reactions = "", {}
            return
        self.reactions = self._get_reactions(lines[-1])
        if self.reactions:
            lines.pop()
        self.content = "\n".join(lines)

    @staticmethod
    def _get_reactions(reaction_line: str) -> dict[str, int]:
        if not reaction_line.startswith("-# "):
            return {}
        d: dict[str, int] = {}
        for s in reaction_line.removeprefix("-# ").split("   "):
            if not (match := _REACTION_REGEX.fullmatch(s)):
                # If any of the reactions don't match, we don't have an actual reaction
                # line; return an empty dictionary to ignore that line as it may just be
                # a similarly-formatted line present in the actual message content
                # itself.
                return {}
            emoji, count = match.groups()
            d[emoji] = int(count)
        return d

    def update(self, message: dc.Message, executor: dc.Member | None) -> None:
        if executor:
            assert isinstance(message.channel, GuildTextChannel)
            self._subtext += (
                f", then from {message.channel.mention} by {executor.mention}"
            )
        for reaction in message.reactions:
            emoji = _format_emoji(reaction.emoji)
            self.reactions.setdefault(emoji, 0)
            self.reactions[emoji] += reaction.count

    @property
    def subtext(self) -> str:
        if not self.reactions:
            return self._subtext
        formatted_reactions = "   ".join(
            f"{emoji} ×{count}"  # noqa: RUF001
            for emoji, count in self.reactions.items()
        )
        return f"-# {formatted_reactions}\n{self._subtext}"


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


def message_can_be_moved(message: dc.Message) -> bool:
    return message.type in NON_SYSTEM_MESSAGE_TYPES


def _find_snowflake(content: str, type_: str) -> tuple[int, int] | tuple[None, None]:
    """
    WARNING: this function does not account for Markdown features such as code blocks
    that may disarm a snowflake.
    """
    # NOTE: while this function could just return tuple[int, int] | None, that makes it
    # less convenient to destructure the return value.
    snowflake = _SNOWFLAKE_REGEX.search(content)
    if snowflake is None or snowflake[1] != type_:
        return None, None
    return int(snowflake[2]), snowflake.span()[0]


class MovedMessageLookupFailed(Enum):
    NOT_FOUND = -1
    NOT_MOVED = -2


class MovedMessage(ExtensibleMessage, dc.WebhookMessage):
    def __init__(
        self, message: dc.WebhookMessage, *, author: dc.Member | None = None
    ) -> None:
        """
        If the subtext does not contain an author, ValueError is thrown. Providing
        `author` may save a web request when using get_original_author().
        """
        super().__init__(message)
        id_ = self._extract_author_id(message.content)
        if id_ is None:
            msg = "not a moved message"
            raise ValueError(msg)
        if author is not None and id_ != author.id:
            # The author in the subtext isn't the same as the author object
            # passed.
            msg = "incorrect author passed"
            raise ValueError(msg)
        self.original_author_id = id_
        self._original_author = author

    @staticmethod
    def _extract_author_id(content: str) -> int | None:
        # HACK: as far as I know, Discord does not provide any way to attach a hidden
        # number to a webhook message, nor does it provide a way to link a webhook
        # message to a user. Thus, this information is extracted from the subtext of
        # moved messages.
        try:
            subtext = content.splitlines()[-1]
        except IndexError:
            return None
        # Heuristics to determine if a message is really a moved message.
        if not subtext.startswith("-# "):
            return None
        # One other thing that could be checked is whether content.splitlines() is at
        # least two elements long; that would backfire when moved media or forwards is
        # passed through this function, however, as those moved messages don't contain
        # anything except the subtext in their `Message.content`.

        # If we have a channel mention, the executor is present; discard that part so
        # that the executor is not accidentally picked as the author.
        _, pos = _find_snowflake(subtext, "#")
        if pos is not None:
            subtext = subtext[:pos]

        # The first user mention in the subtext is the author. If it is not present,
        # _find_snowflake() would return None; pass that right back to the caller.
        snowflake, _ = _find_snowflake(subtext, "@")
        return snowflake

    @classmethod
    async def from_message(
        cls, message: dc.Message, *, webhook_name: str = "Ghostty Moderator"
    ) -> Self | MovedMessageLookupFailed:
        if message.webhook_id is None or isinstance(
            message.channel,
            # These types can't even have a webhook.
            dc.DMChannel | dc.GroupChannel | dc.PartialMessageable,
        ):
            return MovedMessageLookupFailed.NOT_MOVED

        if isinstance(message.channel, dc.Thread):
            thread = message.channel
            if (channel := thread.parent) is None:
                return MovedMessageLookupFailed.NOT_FOUND
        else:
            channel = message.channel
            thread = dc.utils.MISSING

        for webhook in await channel.webhooks():
            if webhook.id == message.webhook_id:
                break
        else:
            return MovedMessageLookupFailed.NOT_MOVED
        if webhook.name != webhook_name:
            # More heuristics to determine if a webhook message is a moved message.
            return MovedMessageLookupFailed.NOT_MOVED

        try:
            return cls(await webhook.fetch_message(message.id, thread=thread))
        except dc.Forbidden:
            return MovedMessageLookupFailed.NOT_FOUND
        except (ValueError, dc.NotFound):
            # NOTE: while it may seem like this function should be returning `NotFound`
            # on `dc.NotFound`, that exception is thrown when the *webhook* couldn't
            # find the associated message, rather than when the message doesn't exist.
            # Since all moved messages are sent by the webhook, this branch symbolizes
            # a message that isn't a moved message.
            return MovedMessageLookupFailed.NOT_MOVED

    async def get_original_author(self) -> dc.Member:
        if self._original_author is not None:
            # Use the cached author.
            return self._original_author
        assert self.guild is not None
        if (author := self.guild.get_member(self.original_author_id)) is None:
            # discord.py doesn't have the member in its user cache, so we need a web
            # request to Discord to get the author.
            author = await self.guild.fetch_member(self.original_author_id)
        # Cache the author.
        self._original_author = author
        return author


@overload
async def move_message_via_webhook(
    webhook: dc.Webhook,
    message: dc.Message,
    executor: dc.Member | None = None,
    *,
    thread: dc.abc.Snowflake = dc.utils.MISSING,
    thread_name: str = dc.utils.MISSING,
    include_move_marks: Literal[True] = True,
) -> MovedMessage: ...


@overload
async def move_message_via_webhook(
    webhook: dc.Webhook,
    message: dc.Message,
    executor: dc.Member | None = None,
    *,
    thread: dc.abc.Snowflake = dc.utils.MISSING,
    thread_name: str = dc.utils.MISSING,
    include_move_marks: Literal[False] = False,
) -> dc.WebhookMessage: ...


async def move_message_via_webhook(  # noqa: PLR0913
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
    display an informative warning message.
    """
    assert message_can_be_moved(message)

    msg_data = await MessageData.scrape(message)

    embeds = [
        *(e for e in message.embeds if not e.url),
        *await asyncio.gather(*map(_get_sticker_embed, message.stickers)),
    ]

    if message.message_snapshots:
        # Only include the first message snapshot.
        snapshot = message.message_snapshots[0]
        forward_embeds, forward_attachments = await _format_forward(snapshot)
        embeds = [*forward_embeds, *embeds]
        msg_data.files.extend(forward_attachments)
    elif reply_embed := await _get_reply_embed(message):
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
        s = _Subtext(msg_data, executor, poll if message.poll is not None else None)
        subtext = s.format() if include_move_marks else s.format_simple()

    content, file = format_or_file(
        _format_interaction(message),
        template=f"{{}}\n{subtext}",
        transform=convert_nitro_emojis,
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


def format_or_file(
    message: str,
    *,
    template: str | None = None,
    transform: Callable[[str], str] | None = None,
) -> tuple[str, dc.File | None]:
    if template is None:
        template = "{}"

    full_message = template.format(message)
    if transform is not None:
        full_message = transform(full_message)

    if len(full_message) > 2000:
        return template.format(""), dc.File(
            BytesIO(message.encode()), filename="content.md"
        )
    return full_message, None
