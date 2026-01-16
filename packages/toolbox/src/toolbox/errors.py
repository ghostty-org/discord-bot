from typing import Any, override

import discord as dc
from loguru import logger

__all__ = (
    "SafeModal",
    "SafeView",
    "handle_error",
    "interaction_error_handler",
)


def handle_error(error: BaseException) -> None:
    logger.exception(error)
    for note in getattr(error, "__notes__", []):
        logger.error(note)
    if isinstance(error, dc.app_commands.CommandInvokeError):
        handle_error(error.original)


async def interaction_error_handler(
    interaction: dc.Interaction, error: Exception, /
) -> None:
    if interaction.extras.get("error_handled", False):
        return
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "Something went wrong :(", ephemeral=True
        )
    else:
        await interaction.followup.send("Something went wrong :(", ephemeral=True)
    handle_error(error)


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
