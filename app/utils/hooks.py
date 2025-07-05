import asyncio
import datetime as dt
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
        self._refs: dict[discord.Message, discord.Message] = {}
        self._frozen = set[discord.Message]()

    def freeze(self, message: discord.Message) -> None:
        self._frozen.add(message)

    def unfreeze(self, message: discord.Message) -> None:
        self._frozen.discard(message)

    def is_frozen(self, message: discord.Message) -> bool:
        return message in self._frozen

    def get(self, original: discord.Message) -> discord.Message | None:
        return self._refs.get(original)

    def link(self, original: discord.Message, reply: discord.Message) -> None:
        if original in self._refs:
            msg = f"message {original.id} already has a reply linked"
            raise ValueError(msg)
        self._refs[original] = reply

    def unlink(self, original: discord.Message) -> None:
        del self._refs[original]

    def get_original_message(self, reply: discord.Message) -> discord.Message | None:
        return next(
            (msg for msg, reply_ in self._refs.items() if reply == reply_), None
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
        [discord.Message],
        Awaitable[
            tuple[str | tuple[str, list[discord.File]] | list[discord.Embed], int]
        ],
    ],
    interactor: Callable[[discord.Message], Awaitable[None]],
    view_type: Callable[[discord.Message, int], discord.ui.View],
    view_timeout: float = 30.0,
) -> Callable[[discord.Message, discord.Message], Awaitable[None]]:
    def extract_content(
        content: str | tuple[str, list[discord.File]] | list[discord.Embed],
    ) -> tuple[str, list[discord.File], list[discord.Embed]]:
        if isinstance(content, list):
            return "", [], content
        if isinstance(content, str):
            return content, [], []
        return content[0], content[1], []

    async def edit_hook(before: discord.Message, after: discord.Message) -> None:
        if before.content == after.content:
            return
        old_objects = await message_processor(before)
        new_objects = await message_processor(after)
        if old_objects == new_objects:
            # Message changed but objects are the same
            return

        if not (reply := linker.get(before)):
            # Some processors use negative values to symbolize special error values, so
            # this can't be `== 0`. An example of this is the snippet_message() function
            # in the file app/components/github_integration/code_links.py.
            if old_objects[1] <= 0 and not linker.is_frozen(before):
                # There were no objects before, so treat this as a new message
                await interactor(after)
            # The message was removed from the linker at some point
            return

        if linker.unlink_if_expired(reply):
            linker.unfreeze(before)
            return

        if linker.is_frozen(before):
            return

        content, count = new_objects
        # `<= 0` for the same reason as the check above
        if count <= 0 and not linker.is_frozen(before):
            # All objects were edited out
            linker.unlink(before)
            await reply.delete()
            return

        content, files, embeds = extract_content(content)
        await reply.edit(
            content=content,
            embeds=embeds,
            attachments=files,
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
        if message.author.bot and (original := linker.get_original_message(message)):
            linker.unlink(original)
            linker.unfreeze(original)
        elif (reply := linker.get(message)) and not linker.is_frozen(message):
            # We don't need to do any unlinking here because reply.delete() triggers
            # on_message_delete which runs the current hook again, and since replies are
            # bot messages, linker.unlink_from_reply(...) handles unlinking for us.
            await reply.delete()
        linker.unfreeze(message)

    return delete_hook
