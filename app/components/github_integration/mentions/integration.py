import discord

from .fmt import entity_message
from app.utils import (
    ItemActions,
    MessageLinker,
    create_delete_hook,
    create_edit_hook,
    is_dm,
    remove_view_after_timeout,
    try_dm,
)

IGNORED_MESSAGE_TYPES = frozenset((
    discord.MessageType.thread_created,
    discord.MessageType.channel_name_change,
))

mention_linker = MessageLinker()


class MentionActions(ItemActions):
    linker = mention_linker
    action_singular = "mentioned this entity"
    action_plural = "mentioned these entities"


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
        view=MentionActions(message, entity_count),
    )
    mention_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


entity_mention_delete_hook = create_delete_hook(linker=mention_linker)

entity_mention_edit_hook = create_edit_hook(
    linker=mention_linker,
    message_processor=entity_message,
    interactor=reply_with_entities,
    view_type=MentionActions,
)
