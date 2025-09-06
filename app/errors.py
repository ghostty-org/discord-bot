import asyncio
import sys
from contextlib import suppress
from typing import Any, cast, override

import discord as dc
from loguru import logger
from sentry_sdk import capture_exception

from app.setup import bot, config


def handle_task_error(task: asyncio.Task[None]) -> None:
    with suppress(asyncio.CancelledError):
        if exc := task.exception():
            handle_error(exc)


def handle_error(error: BaseException) -> None:
    if config.sentry_dsn is not None:
        capture_exception(error)
        return
    logger.exception(error)
    for note in getattr(error, "__notes__", []):
        logger.error(note)
    if isinstance(error, dc.app_commands.CommandInvokeError):
        handle_error(error.original)


@bot.event
async def on_error(*_: object) -> None:
    handle_error(cast("BaseException", sys.exc_info()[1]))


async def interaction_error_handler(
    interaction: dc.Interaction, error: Exception, /
) -> None:
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "Something went wrong :(", ephemeral=True
        )
    else:
        await interaction.followup.send("Something went wrong :(", ephemeral=True)
    handle_error(error)


bot.tree.on_error = interaction_error_handler


class SafeModal(dc.ui.Modal):
    @override
    async def on_error(self, interaction: dc.Interaction, error: Exception, /) -> None:
        return await interaction_error_handler(interaction, error)


class SafeView(dc.ui.View):
    @override
    async def on_error(
        self, interaction: dc.Interaction, error: Exception, item: dc.ui.Item[Any], /
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send("Something went wrong :(", ephemeral=True)
        # else: don't complete interaction,
        # letting discord client send red error message

        handle_error(error)
