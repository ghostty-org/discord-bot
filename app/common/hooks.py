import asyncio
import datetime as dt
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Self

import discord as dc

from app.utils import is_dm, is_mod


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessedMessage:
    item_count: int
    content: str = ""
    files: list[dc.File] = field(default_factory=list[dc.File])
    embeds: list[dc.Embed] = field(default_factory=list[dc.Embed])


async def remove_view_after_timeout(
    message: dc.Message,
    timeout: float = 30.0,  # noqa: ASYNC109
) -> None:
    await asyncio.sleep(timeout)
    with suppress(dc.NotFound, dc.HTTPException):
        await message.edit(view=None)


class MessageLinker:
    def __init__(self) -> None:
        self._refs: dict[dc.Message, dc.Message] = {}
        self._frozen = set[dc.Message]()

    @property
    def expiry_threshold(self) -> dt.datetime:
        return dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24)

    def freeze(self, message: dc.Message) -> None:
        self._frozen.add(message)

    def unfreeze(self, message: dc.Message) -> None:
        self._frozen.discard(message)

    def is_frozen(self, message: dc.Message) -> bool:
        return message in self._frozen

    def get(self, original: dc.Message) -> dc.Message | None:
        return self._refs.get(original)

    def _free_dangling_links(self) -> None:
        # Saving keys to a tuple to avoid a "changed size during iteration" error
        for msg in tuple(self._refs):
            if msg.created_at < self.expiry_threshold:
                self.unlink(msg)
                self.unfreeze(msg)

    def link(self, original: dc.Message, reply: dc.Message) -> None:
        self._free_dangling_links()
        if original in self._refs:
            msg = f"message {original.id} already has a reply linked"
            raise ValueError(msg)
        self._refs[original] = reply

    def unlink(self, original: dc.Message) -> None:
        self._refs.pop(original, None)

    def get_original_message(self, reply: dc.Message) -> dc.Message | None:
        return next(
            (msg for msg, reply_ in self._refs.items() if reply == reply_), None
        )

    def unlink_from_reply(self, reply: dc.Message) -> None:
        if (original_message := self.get_original_message(reply)) is not None:
            self.unlink(original_message)

    def is_expired(self, message: dc.Message) -> bool:
        return message.created_at < self.expiry_threshold


class ItemActions(dc.ui.View):
    linker: MessageLinker
    action_singular: str
    action_plural: str

    def __init__(self, message: dc.Message, item_count: int) -> None:
        super().__init__()
        self.message = message
        self.item_count = item_count

    async def _reject_early(self, interaction: dc.Interaction, action: str) -> bool:
        assert not is_dm(interaction.user)
        if interaction.user.id == self.message.author.id or is_mod(interaction.user):
            return False
        await interaction.response.send_message(
            "Only the person who "
            + (self.action_singular if self.item_count == 1 else self.action_plural)
            + f" can {action} this message.",
            ephemeral=True,
        )
        return True

    @dc.ui.button(label="Delete", emoji="❌")
    async def delete(self, interaction: dc.Interaction, _: dc.ui.Button[Self]) -> None:
        if await self._reject_early(interaction, "remove"):
            return
        assert interaction.message
        await interaction.message.delete()

    @dc.ui.button(label="Freeze", emoji="❄️")  # test: allow-vs16
    async def freeze(
        self, interaction: dc.Interaction, button: dc.ui.Button[Self]
    ) -> None:
        if await self._reject_early(interaction, "freeze"):
            return
        self.linker.freeze(self.message)
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "Message frozen. I will no longer react to"
            " what happens to your original message.",
            ephemeral=True,
        )


def create_edit_hook(
    *,
    linker: MessageLinker,
    message_processor: Callable[[dc.Message], Awaitable[ProcessedMessage]],
    interactor: Callable[[dc.Message], Awaitable[None]],
    view_type: Callable[[dc.Message, int], dc.ui.View],
    view_timeout: float = 30.0,
) -> Callable[[dc.Message, dc.Message], Awaitable[None]]:
    async def edit_hook(before: dc.Message, after: dc.Message) -> None:
        if before.content == after.content:
            return

        if linker.is_expired(before):
            # The original message wasn't updated recently enough
            linker.unlink(before)
            return

        old_output = await message_processor(before)
        new_output = await message_processor(after)
        if old_output == new_output:
            # Message changed but objects are the same
            return

        if not (reply := linker.get(before)):
            if linker.is_frozen(before):
                return
            if old_output.item_count > 0:
                # The message was removed from the linker at some point (most likely
                # when the reply was deleted)
                return
            # There were no objects before, so treat this as a new message
            await interactor(after)
            return

        if linker.is_expired(reply):
            # The original message was updated recently enough, but the edits did not
            # affect the reply, so we can assume it's expired
            linker.unlink_from_reply(reply)
            linker.unfreeze(before)
            return

        if linker.is_frozen(before):
            return

        # Some processors use negative values to symbolize special error values, so this
        # can't be `== 0`. An example of this is the snippet_message() function in the
        # file app/components/github_integration/code_links.py
        if new_output.item_count <= 0:
            # All objects were edited out
            linker.unlink(before)
            await reply.delete()
            return

        await reply.edit(
            content=new_output.content,
            embeds=new_output.embeds,
            attachments=new_output.files,
            suppress=not new_output.embeds,
            view=view_type(after, new_output.item_count),
            allowed_mentions=dc.AllowedMentions.none(),
        )
        await remove_view_after_timeout(reply, view_timeout)

    return edit_hook


def create_delete_hook(
    *, linker: MessageLinker
) -> Callable[[dc.Message], Awaitable[None]]:
    async def delete_hook(message: dc.Message) -> None:
        if message.author.bot and (original := linker.get_original_message(message)):
            linker.unlink(original)
            linker.unfreeze(original)
        elif (reply := linker.get(message)) and not linker.is_frozen(message):
            if linker.is_expired(message):
                linker.unlink(message)
            else:
                # We don't need to do any unlinking here because reply.delete() triggers
                # on_message_delete which runs the current hook again, and since replies
                # are bot messages, linker.unlink(original) above handles it for us.
                await reply.delete()
        linker.unfreeze(message)

    return delete_hook
