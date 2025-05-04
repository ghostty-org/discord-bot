import asyncio
import datetime as dt
from collections import defaultdict
from collections.abc import Awaitable, Callable
from contextlib import suppress

import discord


async def remove_view_after_timeout(
    message: discord.Message,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> None:
    await asyncio.sleep(timeout)
    with suppress(discord.NotFound, discord.HTTPException):
        await message.edit(view=None)


class MessageLinker:
    def __init__(self) -> None:
        self._refs = defaultdict[discord.Message, list[discord.Message]](list)

    def get(self, original: discord.Message) -> list[discord.Message]:
        return self._refs[original]

    def link(self, original: discord.Message, *replies: discord.Message) -> None:
        self._refs[original].extend(replies)

    def unlink(self, original: discord.Message) -> None:
        del self._refs[original]

    def get_original_message(self, reply: discord.Message) -> discord.Message | None:
        return next(
            (msg for msg, replies in self._refs.items() if reply in replies), None
        )

    def unlink_from_reply(self, reply: discord.Message) -> None:
        if (original_message := self.get_original_message(reply)) is not None:
            self.unlink(original_message)

    def unlink_if_expired(self, reply: discord.Message) -> bool:
        # Stop reacting to message updates after 24 hours
        last_updated = reply.edited_at or reply.created_at
        if dt.datetime.now(tz=dt.UTC) - last_updated > dt.timedelta(hours=24):
            self.unlink_from_reply(reply)
            return True
        return False


def create_edit_hook(
    *,
    linker: MessageLinker,
    message_processor: Callable[
        [discord.Message], Awaitable[tuple[str | list[discord.Embed], int]]
    ],
    interactor: Callable[[discord.Message], Awaitable[None]],
    view_type: Callable[[discord.Message, int], discord.ui.View],
    view_timeout: float = 30.0,
) -> Callable[[discord.Message, discord.Message], Awaitable[None]]:
    def extract_content(
        content: str | list[discord.Embed],
    ) -> tuple[str, list[discord.Embed]]:
        if isinstance(content, list):
            return "", content
        return content, []

    async def edit_hook(before: discord.Message, after: discord.Message) -> None:
        if before.content == after.content:
            return
        old_objects = await message_processor(before)
        new_objects = await message_processor(after)
        if old_objects == new_objects:
            # Message changed but objects are the same
            return

        if not (replies := linker.get(before)):
            if not old_objects[1]:
                # There were no objects before, so treat this as a new message
                await interactor(after)
            # The message was removed from the linker at some point
            return

        reply = replies[0]
        content, count = new_objects
        if not count:
            # All objects were edited out
            linker.unlink(before)
            await reply.delete()
            return

        if linker.unlink_if_expired(reply):
            return

        content, embeds = extract_content(content)
        await reply.edit(
            content=content,
            embeds=embeds,
            suppress=not embeds,
            view=view_type(after, count),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await remove_view_after_timeout(reply, view_timeout)

    return edit_hook


def create_delete_hook(
    *, linker: MessageLinker
) -> Callable[[discord.Message], Awaitable[None]]:
    async def delete_hook(message: discord.Message) -> None:
        if message.author.bot:
            linker.unlink_from_reply(message)
        elif replies := linker.get(message):
            # We don't need to do any unlinking here because reply.delete() triggers
            # on_message_delete which runs the current hook again, and since replies are
            # bot messages, linker.unlink_from_reply(...) handles unlinking for us.
            for reply in replies:
                await reply.delete()

    return delete_hook
