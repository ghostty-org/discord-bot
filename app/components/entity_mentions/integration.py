from __future__ import annotations

import discord

from .fmt import entity_message
from app.utils import MessageLinker, is_dm, is_mod, remove_view_after_timeout, try_dm

IGNORED_MESSAGE_TYPES = frozenset(
    (discord.MessageType.thread_created, discord.MessageType.channel_name_change)
)


class DeleteMention(discord.ui.View):
    def __init__(self, message: discord.Message, entity_count: int) -> None:
        super().__init__()
        self.message = message
        self.plural = entity_count > 1

    @discord.ui.button(
        label="Delete",
        emoji="🗑️",
        style=discord.ButtonStyle.gray,
    )
    async def delete(
        self, interaction: discord.Interaction, _: discord.ui.Button[DeleteMention]
    ) -> None:
        assert not is_dm(interaction.user)
        if interaction.user.id == self.message.author.id or is_mod(interaction.user):
            assert interaction.message
            await interaction.message.delete()
            mention_linker.unlink_from_reply(interaction.message)
            return

        await interaction.response.send_message(
            "Only the person who mentioned "
            + ("these entities" if self.plural else "this entity")
            + " can remove this message.",
            ephemeral=True,
        )


mention_linker = MessageLinker()


async def reply_with_entities(message: discord.Message) -> None:
    if message.author.bot or message.type in IGNORED_MESSAGE_TYPES:
        return

    if is_dm(message.author):
        await try_dm(
            message.author,
            "You can only mention entities in the Ghostty server.",
        )
        return

    msg_content, entity_count = await entity_message(message)
    if not entity_count:
        return

    sent_message = await message.reply(
        msg_content,
        suppress_embeds=True,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
        view=DeleteMention(message, entity_count),
    )
    mention_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


async def entity_mention_delete_handler(message: discord.Message) -> None:
    if message.author.bot:
        mention_linker.unlink_from_reply(message)
    elif replies := mention_linker.get(message):
        for reply in replies:
            await reply.delete()


async def entity_mention_edit_handler(
    before: discord.Message, after: discord.Message
) -> None:
    if before.content == after.content:
        return
    old_entities = await entity_message(before)
    new_entities = await entity_message(after)
    if old_entities == new_entities:
        # Message changed but mentions are the same
        return

    if not (replies := mention_linker.get(before)):
        if not old_entities[1]:
            # There were no mentions before, so treat this as a new message
            await reply_with_entities(after)
        # The message was removed from the M2M map at some point
        return

    reply = replies[0]
    content, count = new_entities
    if not count:
        # All mentions were edited out
        mention_linker.unlink(before)
        await reply.delete()
        return

    if mention_linker.unlink_if_expired(reply):
        return

    await reply.edit(
        content=content,
        suppress=True,
        view=DeleteMention(after, count),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await remove_view_after_timeout(reply)
