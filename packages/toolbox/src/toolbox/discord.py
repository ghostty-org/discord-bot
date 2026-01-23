import asyncio
import re
from contextlib import suppress
from io import BytesIO
from textwrap import shorten
from typing import TYPE_CHECKING, Any, TypeIs

import discord as dc
from discord.app_commands import Choice
from loguru import logger

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Callable, Iterable

__all__ = (
    "SUPPORTED_IMAGE_FORMATS",
    "Account",
    "GuildTextChannel",
    "dynamic_timestamp",
    "escape_special",
    "format_or_file",
    "generate_autocomplete",
    "is_dm",
    "post_has_tag",
    "post_is_solved",
    "pretty_print_account",
    "safe_edit",
    "suppress_embeds_after_delay",
    "try_dm",
)


_INVITE_LINK_REGEX = re.compile(r"\b(?:https?://)?(discord\.gg/[^\s]+)\b")
_ORDERED_LIST_REGEX = re.compile(r"^(\d+)\. (.*)")

# A list of image formats supported by Discord, in the form of their file extension
# (including the leading dot).
SUPPORTED_IMAGE_FORMATS = frozenset({".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"})

type Account = dc.User | dc.Member
# Not a PEP 695 type alias because of runtime isinstance() checks
GuildTextChannel = dc.TextChannel | dc.Thread

safe_edit = suppress(dc.NotFound, dc.HTTPException)


def dynamic_timestamp(dt: dt.datetime, fmt: str | None = None) -> str:
    fmt = f":{fmt}" if fmt is not None else ""
    return f"<t:{int(dt.timestamp())}{fmt}>"


def is_dm(account: Account) -> TypeIs[dc.User]:
    return not isinstance(account, dc.Member)


async def try_dm(account: Account, content: str, **extras: Any) -> None:
    if account.bot:
        logger.warning(
            "attempted to DM {}, who is a bot", pretty_print_account(account)
        )
        return
    try:
        await account.send(content, **extras)
    except dc.Forbidden:
        logger.error("failed to DM {} with: {}", account, shorten(content, width=50))


def post_has_tag(post: dc.Thread, substring: str) -> bool:
    return any(substring in tag.name.casefold() for tag in post.applied_tags)


def post_is_solved(post: dc.Thread) -> bool:
    return any(
        post_has_tag(post, tag)
        for tag in ("solved", "moved to github", "duplicate", "stale")
    )


def escape_special(content: str) -> str:
    """
    Escape all text that Discord considers to be special.

    Consider adding the following kwargs to `send()`-like functions too:
        suppress_embeds=True,
        allowed_mentions=dc.AllowedMentions.none(),
    """
    escaped = dc.utils.escape_mentions(content)
    escaped = dc.utils.escape_markdown(escaped)
    # escape_mentions() doesn't deal with anything other than username mentions.
    escaped = escaped.replace("<", r"\<").replace(">", r"\>")
    # Invite links are not embeds and are hence not suppressed by that flag.
    escaped = _INVITE_LINK_REGEX.sub(r"<https://\g<1>>", escaped)
    # escape_markdown() doesn't deal with ordered lists.
    return "\n".join(
        _ORDERED_LIST_REGEX.sub(r"\g<1>\. \g<2>", line) for line in escaped.splitlines()
    )


async def suppress_embeds_after_delay(message: dc.Message, delay: float = 5.0) -> None:
    logger.trace("waiting {}s to suppress embeds of {}", delay, message)
    await asyncio.sleep(delay)
    with safe_edit:
        logger.debug("suppressing embeds of {}", message)
        await message.edit(suppress=True)


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


def pretty_print_account(user: Account) -> str:
    return f"<{user.name} - {user.id}>"


def generate_autocomplete(
    current: str, choices: Iterable[str | tuple[str, str]]
) -> list[Choice[str]]:
    padded = (c if isinstance(c, tuple) else (c, c) for c in choices)
    current = current.casefold()
    return sorted(
        (
            Choice(name=name, value=value)
            for name, value in padded
            if current in name.casefold()
        ),
        key=lambda c: c.name,
    )[:25]  # Discord only allows 25 options for autocomplete
