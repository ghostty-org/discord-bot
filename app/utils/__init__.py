from __future__ import annotations

import re
from textwrap import shorten
from typing import TYPE_CHECKING, Any

import discord as dc

from .message_data import MAX_ATTACHMENT_SIZE, ExtensibleMessage, MessageData, get_files
from app.setup import config

__all__ = (
    "MAX_ATTACHMENT_SIZE",
    "Account",
    "ExtensibleMessage",
    "MessageData",
    "aenumerate",
    "dynamic_timestamp",
    "escape_special",
    "get_files",
    "is_attachment_only",
    "is_dm",
    "is_helper",
    "is_mod",
    "post_has_tag",
    "post_is_solved",
    "truncate",
    "try_dm",
)

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import AsyncIterator

    from typing_extensions import TypeIs


_INVITE_LINK_REGEX = re.compile(r"\b(?:https?://)?(discord\.gg/[^\s]+)\b")
_ORDERED_LIST_REGEX = re.compile(r"^(\d+)\. (.*)")

type Account = dc.User | dc.Member
# Not a PEP 695 type alias because of runtime isinstance() checks
GuildTextChannel = dc.TextChannel | dc.Thread


def truncate(s: str, length: int, *, suffix: str = "…") -> str:
    if len(s) <= length:
        return s
    return s[: length - len(suffix)] + suffix


def dynamic_timestamp(dt: dt.datetime, fmt: str | None = None) -> str:
    fmt = f":{fmt}" if fmt is not None else ""
    return f"<t:{int(dt.timestamp())}{fmt}>"


def is_dm(account: Account) -> TypeIs[dc.User]:
    return not isinstance(account, dc.Member)


def is_mod(member: dc.Member) -> bool:
    return member.get_role(config.MOD_ROLE_ID) is not None


def is_helper(member: dc.Member) -> bool:
    return member.get_role(config.HELPER_ROLE_ID) is not None


async def try_dm(account: Account, content: str, **extras: Any) -> None:
    if account.bot:
        return
    try:
        await account.send(content, **extras)
    except dc.Forbidden:
        print(f"Failed to DM {account} with: {shorten(content, width=50)}")


def post_has_tag(post: dc.Thread, substring: str) -> bool:
    return any(substring in tag.name.casefold() for tag in post.applied_tags)


def post_is_solved(post: dc.Thread) -> bool:
    return any(
        post_has_tag(post, tag)
        for tag in ("solved", "moved to github", "duplicate", "stale")
    )


async def aenumerate[T](
    it: AsyncIterator[T], start: int = 0
) -> AsyncIterator[tuple[int, T]]:
    i = start
    async for x in it:
        yield i, x
        i += 1


def escape_special(content: str) -> str:
    """
    Escape all text that Discord considers to be special.

    Consider adding the following kwargs to `send()`-like functions too:
        suppress_embeds=True,
        allowed_mentions=discord.AllowedMentions.none(),
    """
    escaped = dc.utils.escape_mentions(content)
    escaped = dc.utils.escape_markdown(escaped)
    # escape_mentions() doesn't deal with anything other than username mentions.
    escaped = escaped.replace("<", r"\<").replace(">", r"\>")
    # Invite links are not embeds and are hence not suppressed by that flag.
    escaped = _INVITE_LINK_REGEX.sub(r"<https://\1>", escaped)
    # escape_markdown() doesn't deal with ordered lists.
    return "\n".join(
        _ORDERED_LIST_REGEX.sub(r"\1\. \2", line) for line in escaped.splitlines()
    )


def is_attachment_only(
    message: dc.Message, *, preprocessed_content: str | None = None
) -> bool:
    if preprocessed_content is None:
        preprocessed_content = message.content
    return bool(message.attachments) and not any((
        message.components,
        preprocessed_content,
        message.embeds,
        message.poll,
        message.stickers,
    ))
