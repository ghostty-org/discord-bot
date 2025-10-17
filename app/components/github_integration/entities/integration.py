from __future__ import annotations

import asyncio
from collections import defaultdict
from functools import partial
from itertools import chain
from typing import TYPE_CHECKING, final, override

import discord as dc
from discord.ext import commands, tasks

from .cache import entity_cache
from .fmt import entity_message, extract_entities
from .resolution import ENTITY_REGEX
from app.common.linker import ItemActions, MessageLinker, remove_view_after_delay
from app.components.github_integration.models import Entity
from app.utils import (
    REGULAR_MESSAGE_TYPES,
    is_dm,
    safe_edit,
    suppress_embeds_after_delay,
)

if TYPE_CHECKING:
    from app.bot import GhosttyBot


@final
class EntityActions(ItemActions):
    action_singular = "mentioned this entity"
    action_plural = "mentioned these entities"


@final
class GitHubEntities(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.linker = MessageLinker()
        EntityActions.linker = self.linker

        self.update_recent_mentions.start()

    @override
    async def cog_unload(self) -> None:
        self.update_recent_mentions.cancel()

    @tasks.loop(hours=1)
    async def update_recent_mentions(self) -> None:
        self.linker.free_dangling_links()
        entity_to_message_map = defaultdict[Entity, list[dc.Message]](list)

        # Gather all currently actively mentioned entities
        for msg in self.linker.refs:
            with safe_edit:
                entities = await extract_entities(msg)
                for entity in entities:
                    entity_to_message_map[entity].append(msg)

        # Check which entities changed
        for entity in tuple(entity_to_message_map):
            key = (entity.owner, entity.repo_name, entity.number)
            await entity_cache.fetch(key)
            refreshed_entity = await entity_cache.get(key)
            if entity == refreshed_entity:
                entity_to_message_map.pop(entity)

        # Deduplicate remaining messages
        messages_to_update = set(chain.from_iterable(entity_to_message_map.values()))

        for msg in messages_to_update:
            reply = self.linker.get(msg)
            assert reply is not None

            new_output = await entity_message(self.bot, msg)

            with safe_edit:
                await reply.edit(
                    content=new_output.content,
                    allowed_mentions=dc.AllowedMentions.none(),
                )

    @update_recent_mentions.before_loop
    async def before_update_recent_mentions(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener("on_message")
    async def reply_with_entities(self, message: dc.Message) -> None:
        if (
            message.author.bot
            or message.type not in REGULAR_MESSAGE_TYPES
            or self.bot.fails_message_filters(message)
            or not ENTITY_REGEX.search(message.content)
        ):
            return

        if is_dm(message.author):
            return

        output = await entity_message(self.bot, message)
        if not output.item_count:
            return

        sent_message = await message.reply(
            output.content,
            suppress_embeds=True,
            mention_author=False,
            allowed_mentions=dc.AllowedMentions.none(),
            view=EntityActions(message, output.item_count),
        )
        self.linker.link(message, sent_message)

        async with asyncio.TaskGroup() as group:
            group.create_task(remove_view_after_delay(sent_message))
            # The suppress is done here (instead of in resolve_repo_signatures) to
            # prevent blocking I/O for 5 seconds. The regex is run again here because
            # (1) modifying the signature of resolve_repo_signatures to accommodate that
            # would make it ugly (2) we can't modify entity_message's signature as the
            # hook system requires it to return a ProcessedMessage.
            if any(m["site"] for m in ENTITY_REGEX.finditer(message.content)):
                group.create_task(suppress_embeds_after_delay(message))

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=partial(entity_message, self.bot),
            interactor=self.reply_with_entities,
            view_type=EntityActions,
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(GitHubEntities(bot))
