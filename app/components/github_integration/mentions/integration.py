import discord as dc

from .fmt import entity_message
from app.common.hooks import (
    ItemActions,
    MessageLinker,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)
from app.utils import (
    is_dm,
    try_dm,
)

IGNORED_MESSAGE_TYPES = frozenset((
    dc.MessageType.thread_created,
    dc.MessageType.channel_name_change,
))

mention_linker = MessageLinker()


class MentionActions(ItemActions):
    linker = mention_linker
    action_singular = "mentioned this entity"
    action_plural = "mentioned these entities"


async def reply_with_entities(message: dc.Message) -> None:
    if message.author.bot or message.type in IGNORED_MESSAGE_TYPES:
        return

    if is_dm(message.author):
        await try_dm(
            message.author,
            "You can only mention entities in the Ghostty server.",
        )
        return

    output = await entity_message(message)
    if not output.item_count:
        return

    sent_message = await message.reply(
        output.content,
        suppress_embeds=True,
        mention_author=False,
        allowed_mentions=dc.AllowedMentions.none(),
        view=MentionActions(message, output.item_count),
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
