import asyncio
import datetime as dt
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Self, final

import discord as dc
from loguru import logger

from toolbox.discord import is_dm, pretty_print_account, safe_edit
from toolbox.errors import SafeView

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = (
    "ItemActions",
    "MessageLinker",
    "ProcessedMessage",
    "remove_view_after_delay",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessedMessage:
    item_count: int
    content: str = ""
    files: list[dc.File] = field(default_factory=list[dc.File])
    embeds: list[dc.Embed] = field(default_factory=list[dc.Embed])


async def remove_view_after_delay(message: dc.Message, delay: float = 30.0) -> None:
    logger.trace("waiting {}s to remove view of {}", delay, message)
    await asyncio.sleep(delay)
    with safe_edit:
        logger.debug("removing view of {}", message)
        await message.edit(view=None)


@final
class MessageLinker:
    def __init__(self) -> None:
        self._refs: dict[dc.Message, dc.Message] = {}
        self._frozen = set[dc.Message]()

    @property
    def refs(self) -> MappingProxyType[dc.Message, dc.Message]:
        return MappingProxyType(self._refs)

    @property
    def expiry_threshold(self) -> dt.datetime:
        return dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24)

    def freeze(self, message: dc.Message) -> None:
        logger.debug("freezing message {}", message)
        self._frozen.add(message)

    def unfreeze(self, message: dc.Message) -> None:
        logger.debug("unfreezing message {}", message)
        self._frozen.discard(message)

    def is_frozen(self, message: dc.Message) -> bool:
        return message in self._frozen

    def get(self, original: dc.Message) -> dc.Message | None:
        return self._refs.get(original)

    def free_dangling_links(self) -> None:
        # Saving keys to a tuple to avoid a "changed size during iteration" error
        for msg in tuple(self._refs):
            if msg.created_at < self.expiry_threshold:
                logger.trace("message {} is dangling; freeing", msg)
                self.unlink(msg)
                self.unfreeze(msg)

    def link(self, original: dc.Message, reply: dc.Message) -> None:
        logger.debug("linking {} to {}", original, reply)
        self.free_dangling_links()
        if original in self._refs:
            msg = f"message {original.id} already has a reply linked"
            raise ValueError(msg)
        self._refs[original] = reply

    def unlink(self, original: dc.Message) -> None:
        logger.debug("unlinking {}", original)
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

    async def delete(self, message: dc.Message) -> None:
        if message.author.bot and (original := self.get_original_message(message)):
            logger.debug(
                "reply {} deleted; unlinking original message {}", message, original
            )
            self.unlink(original)
            self.unfreeze(original)
        elif (reply := self.get(message)) and not self.is_frozen(message):
            if self.is_expired(message):
                logger.debug("message {} has expired; unlinking", message)
                self.unlink(message)
            else:
                logger.debug("deleting reply {} of message {}", reply, message)
                # We don't need to do any unlinking here because reply.delete() triggers
                # on_message_delete which runs the current hook again, and since replies
                # are bot messages, self.unlink(original) above handles it for us.
                await reply.delete()
        self.unfreeze(message)

    async def edit(  # noqa: PLR0913
        self,
        before: dc.Message,
        after: dc.Message,
        *,
        message_processor: Callable[[dc.Message], Awaitable[ProcessedMessage]],
        interactor: Callable[[dc.Message], Awaitable[None]],
        view_type: Callable[[dc.Message, int], dc.ui.View],
        view_timeout: float = 30.0,
    ) -> None:
        if before.author.bot:
            logger.trace("ignoring bot message edit")
            return
        if before.content == after.content:
            logger.trace("content did not change")
            return

        if self.is_expired(before):
            # The original message wasn't updated recently enough
            logger.debug("message {} has expired; unlinking", before)
            self.unlink(before)
            return

        old_output = await message_processor(before)
        new_output = await message_processor(after)
        if old_output == new_output:
            logger.trace("message changed but objects are the same")
            return

        logger.debug(
            "running edit hook for {}",
            getattr(message_processor, "__name__", message_processor),
        )

        if not (reply := self.get(before)):
            if self.is_frozen(before):
                logger.trace("skipping frozen message {}", before)
                return
            if old_output.item_count > 0:
                logger.trace(
                    "skipping message that was removed from the linker at some point "
                    "(most likely when the reply was deleted)"
                )
                return
            logger.debug("no objects were present before, treating as new message")
            await interactor(after)
            return

        if self.is_frozen(before):
            logger.trace("skipping frozen message {}", before)
            return

        # Some processors use negative values to symbolize special error values, so this
        # can't be `== 0`. An example of this is the snippet_message() function in the
        # file app/components/github_integration/code_links.py
        if new_output.item_count <= 0:
            logger.debug("all objects were edited out")
            self.unlink(before)
            await reply.delete()
            return

        logger.debug("editing message {} with updated objects", reply)
        await reply.edit(
            content=new_output.content,
            embeds=new_output.embeds,
            attachments=new_output.files,
            suppress=not new_output.embeds,
            view=view_type(after, new_output.item_count),
            allowed_mentions=dc.AllowedMentions.none(),
        )
        await remove_view_after_delay(reply, view_timeout)


class ItemActions(SafeView):
    linker: ClassVar[MessageLinker]
    action_singular: ClassVar[str]
    action_plural: ClassVar[str]
    message: dc.Message
    item_count: int

    def __init__(self, message: dc.Message, item_count: int) -> None:
        super().__init__()
        self.message = message
        self.item_count = item_count

    async def _reject_early(self, interaction: dc.Interaction, action: str) -> bool:
        assert not is_dm(interaction.user)
        user_str = pretty_print_account(interaction.user)
        if interaction.user.id == self.message.author.id:
            logger.trace("{} run by author {}", action, user_str)
            return False
        logger.debug("{} run by non-author {}", action, user_str)
        await interaction.response.send_message(
            "Only the person who "
            + (self.action_singular if self.item_count == 1 else self.action_plural)
            + f" can {action} this message.",
            ephemeral=True,
        )
        return True

    @dc.ui.button(label="Delete", emoji="❌")
    async def delete(self, interaction: dc.Interaction, _: dc.ui.Button[Self]) -> None:
        logger.trace("delete button pressed on message {}", interaction.message)
        if await self._reject_early(interaction, "remove"):
            return
        assert interaction.message
        await interaction.message.delete()

    @dc.ui.button(label="Freeze", emoji="❄️")  # test: allow-vs16
    async def freeze(
        self, interaction: dc.Interaction, button: dc.ui.Button[Self]
    ) -> None:
        logger.trace("freeze button pressed on message {}", self.message)
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
