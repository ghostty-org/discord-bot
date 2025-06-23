from __future__ import annotations

import re
from textwrap import shorten
from typing import TYPE_CHECKING, Any, Self

import discord

from .cache import TTRCache
from .hooks import (
    MessageLinker,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)
from .message_data import ExtensibleMessage, MessageData
from .webhooks import (
    NON_SYSTEM_MESSAGE_TYPES,
    SUPPORTED_IMAGE_FORMATS,
    GuildTextChannel,
    MovedMessage,
    MovedMessageLookupFailed,
    SplitSubtext,
    dynamic_timestamp,
    format_or_file,
    get_ghostty_guild,
    get_or_create_webhook,
    message_can_be_moved,
    move_message_via_webhook,
    truncate,
)
from app.setup import config

__all__ = (
    "NON_SYSTEM_MESSAGE_TYPES",
    "SUPPORTED_IMAGE_FORMATS",
    "Account",
    "DeleteMessage",
    "ExtensibleMessage",
    "GuildTextChannel",
    "MessageData",
    "MessageLinker",
    "MovedMessage",
    "MovedMessageLookupFailed",
    "SplitSubtext",
    "TTRCache",
    "create_delete_hook",
    "create_edit_hook",
    "dynamic_timestamp",
    "escape_special",
    "format_or_file",
    "get_ghostty_guild",
    "get_or_create_webhook",
    "is_dm",
    "is_helper",
    "is_mod",
    "message_can_be_moved",
    "move_message_via_webhook",
    "remove_view_after_timeout",
    "truncate",
    "try_dm",
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from typing_extensions import TypeIs


_INVITE_LINK_REGEX = re.compile(r"\b(?:https?://)?(discord\.gg/[^\s]+)\b")
_ORDERED_LIST_REGEX = re.compile(r"^(\d+)\. (.*)")

type Account = discord.User | discord.Member


class DeleteMessage(discord.ui.View):
    linker: MessageLinker
    action_singular: str
    action_plural: str

    def __init__(self, message: discord.Message, item_count: int) -> None:
        super().__init__()
        self.message = message
        self.item_count = item_count

    @discord.ui.button(
        label="Delete",
        emoji="🗑️",  # test: allow-vs16
        style=discord.ButtonStyle.gray,
    )
    async def delete(
        self, interaction: discord.Interaction, _: discord.ui.Button[Self]
    ) -> None:
        assert not is_dm(interaction.user)
        if interaction.user.id == self.message.author.id or is_mod(interaction.user):
            assert interaction.message
            await interaction.message.delete()
            self.linker.unlink_from_reply(interaction.message)
            return

        await interaction.response.send_message(
            "Only the person who "
            + (self.action_singular if self.item_count == 1 else self.action_plural)
            + " can remove this message.",
            ephemeral=True,
        )


def is_dm(account: Account) -> TypeIs[discord.User]:
    return not isinstance(account, discord.Member)


def is_mod(member: discord.Member) -> bool:
    return member.get_role(config.MOD_ROLE_ID) is not None


def is_helper(member: discord.Member) -> bool:
    return member.get_role(config.HELPER_ROLE_ID) is not None


async def try_dm(account: Account, content: str, **extras: Any) -> None:
    if account.bot:
        return
    try:
        await account.send(content, **extras)
    except discord.Forbidden:
        print(f"Failed to DM {account} with: {shorten(content, width=50)}")


def post_has_tag(post: discord.Thread, substring: str) -> bool:
    return any(substring in tag.name.casefold() for tag in post.applied_tags)


def post_is_solved(post: discord.Thread) -> bool:
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
    escaped = discord.utils.escape_mentions(content)
    escaped = discord.utils.escape_markdown(escaped)
    # escape_mentions() doesn't deal with anything other than username
    # mentions.
    escaped = escaped.replace("<", r"\<").replace(">", r"\>")
    # Invite links are not embeds and are hence not suppressed by that flag.
    escaped = _INVITE_LINK_REGEX.sub(r"<https://\1>", escaped)
    # escape_markdown() doesn't deal with ordered lists.
    return "\n".join(
        _ORDERED_LIST_REGEX.sub(r"\1\. \2", line) for line in escaped.splitlines()
    )
