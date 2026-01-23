import re
from enum import IntEnum
from typing import Self, final

import discord as dc

from toolbox.messages import ExtensibleMessage

_SNOWFLAKE_REGEX = re.compile(r"<(\D{0,2})(\d+)>", re.ASCII)


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


class MovedMessageLookupFailed(IntEnum):
    NOT_FOUND = -1
    NOT_MOVED = -2


@final
class MovedMessage(ExtensibleMessage, dc.WebhookMessage):  # pyright: ignore[reportUnsafeMultipleInheritance]
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
            # The author in the subtext isn't the same as the author object passed.
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
        cls,
        message: dc.Message,
        *,
        webhook_name: str = "Ghostty Moderator",
        author: dc.Member | None = None,
    ) -> Self | MovedMessageLookupFailed:
        """
        Providing `author` may save a web request when using get_original_author().
        ValueError is thrown if the provided `author`'s ID does not match the ID in the
        message's subtext.
        """
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

        # Before making any API calls, do an early check for the author in the subtext.
        # NOTE: ensure this precedes all await points in this function! Otherwise, the
        # reason for duplicating these checks, reducing slow calls before the check is
        # run, may be neutered.
        if (author_id := cls._extract_author_id(message.content)) is None:
            return MovedMessageLookupFailed.NOT_MOVED
        if author is not None and author_id != author.id:
            # The author in the subtext isn't the same as the author object passed.
            msg = "incorrect author passed"
            raise ValueError(msg)

        for webhook in await channel.webhooks():
            if webhook.id == message.webhook_id:
                break
        else:
            return MovedMessageLookupFailed.NOT_MOVED
        if webhook.name != webhook_name:
            # More heuristics to determine if a webhook message is a moved message.
            return MovedMessageLookupFailed.NOT_MOVED

        try:
            return cls(
                await webhook.fetch_message(message.id, thread=thread), author=author
            )
        except dc.Forbidden:
            return MovedMessageLookupFailed.NOT_FOUND
        except dc.NotFound:
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
