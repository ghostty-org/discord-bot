from __future__ import annotations

from typing import TYPE_CHECKING, Any, final

import discord as dc
from discord.ext import commands
from loguru import logger

from app.utils import pretty_print_account, try_dm

if TYPE_CHECKING:
    from app.bot import GhosttyBot


@final
class Developer(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

    @commands.command(name="sync", description="Sync command tree.")
    async def sync(self, ctx: commands.Context[Any]) -> None:
        if not self.bot.is_ghostty_mod(ctx.author):
            logger.debug(
                "!sync called by {} who is not a mod", pretty_print_account(ctx.author)
            )
            return

        logger.info("syncing command tree")
        await self.bot.tree.sync()
        await try_dm(ctx.author, "Command tree synced.")

    @dc.app_commands.command(name="status", description="View Ghostty Bot's status.")
    @dc.app_commands.guild_only()
    # Hide interaction from non-mods
    @dc.app_commands.default_permissions(ban_members=True)
    async def status(self, interaction: dc.Interaction) -> None:
        # The client-side check with `default_permissions` isn't guaranteed to work.
        if not self.bot.is_ghostty_mod(interaction.user):
            await interaction.response.send_message(
                "Only mods can use this command.", ephemeral=True
            )
        await interaction.response.send_message(
            await self.bot.bot_status.status_message(), ephemeral=True
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(Developer(bot))
