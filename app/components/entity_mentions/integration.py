import datetime as dt

import discord

from app.utils import is_dm, is_mod, remove_view_after_timeout, try_dm

from .fmt import entity_message

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
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        assert not is_dm(interaction.user)
        if interaction.user.id == self.message.author.id or is_mod(interaction.user):
            assert interaction.message
            await interaction.message.delete()
            _unlink_original_message(interaction.message)
            return

        await interaction.response.send_message(
            "Only the person who mentioned "
            + ("these entities" if self.plural else "this entity")
            + " can remove this message.",
            ephemeral=True,
        )


message_to_mentions: dict[discord.Message, discord.Message] = {}


def _unlink_original_message(message: discord.Message) -> None:
    original_message = next(
        (msg for msg, reply in message_to_mentions.items() if reply == message),
        None,
    )
    if original_message is not None:
        del message_to_mentions[original_message]


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
        msg_content, mention_author=False, view=DeleteMention(message, entity_count)
    )
    message_to_mentions[message] = sent_message
    await remove_view_after_timeout(sent_message)


async def entity_mention_delete_handler(message: discord.Message) -> None:
    if message.author.bot:
        _unlink_original_message(message)
    elif (reply := message_to_mentions.get(message)) is not None:
        await reply.delete()


async def entity_mention_edit_handler(
    before: discord.Message, after: discord.Message
) -> None:
    if before.content == after.content:
        return
    old_entites = await entity_message(before)
    new_entities = await entity_message(after)
    if old_entites == new_entities:
        # Message changed but mentions are the same
        return

    if (reply := message_to_mentions.get(before)) is None:
        if not old_entites[1]:
            # There were no mentions before, so treat this as a new message
            await reply_with_entities(after)
        # The message was removed from the M2M map at some point
        return

    content, count = new_entities
    if not count:
        # All mentions were edited out
        del message_to_mentions[before]
        await reply.delete()
        return

    # If the message was edited (or created, if never edited) more than 24 hours ago,
    # stop reacting to it and remove its M2M entry.
    last_updated = dt.datetime.now(tz=dt.UTC) - (reply.edited_at or reply.created_at)
    if last_updated > dt.timedelta(hours=24):
        del message_to_mentions[before]
        return

    await reply.edit(
        content=content,
        view=DeleteMention(after, count),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await remove_view_after_timeout(reply)
