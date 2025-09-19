from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, final

import discord as dc
from discord.app_commands import Choice
from discord.ext import commands
from loguru import logger

from app.utils import pretty_print_account, try_dm

if TYPE_CHECKING:
    from app.bot import GhosttyBot


@final
class Developer(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

    async def existing_extension_autocomplete(
        self, _: dc.Interaction, current: str
    ) -> list[Choice[str]]:
        return [
            Choice(name=name, value=cog_module.__name__)
            for name, cog in (c for c in self.bot.cogs.items())
            if (
                current.casefold() in name.casefold()
                and (cog_module := inspect.getmodule(cog))
            )
        ]

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
            return
        await interaction.response.send_message(
            await self.bot.bot_status.status_message(), ephemeral=True
        )

    @dc.app_commands.command(description="Reload bot extensions.")
    @dc.app_commands.guild_only()
    # Hide interaction from non-mods
    @dc.app_commands.default_permissions(ban_members=True)
    @dc.app_commands.autocomplete(extension=existing_extension_autocomplete)
    async def reload(
        self, interaction: dc.Interaction, extension: str | None = None
    ) -> None:
        # The client-side check with `default_permissions` isn't guaranteed to work.
        if not self.bot.is_ghostty_mod(interaction.user):
            await interaction.response.send_message(
                "Only mods can use this command.", ephemeral=True
            )
            return

        # If no extension is provided, reload all extensions
        if extension:
            if not self.bot.is_valid_extension(extension):
                await interaction.response.send_message(
                    f"{extension} is an invalid / unknown extension.", ephemeral=True
                )
                return
            extensions = [extension]
        else:
            extensions = self.bot.get_component_extension_names()
        reloaded_cogs: list[str] = []

        await interaction.response.defer(thinking=True, ephemeral=True)
        for cog in extensions:
            await self.bot.unload_extension(cog)
            await self.bot.load_extension(cog)
            reloaded_cogs.append(cog)
        await interaction.followup.send(f"Reloaded {reloaded_cogs}", ephemeral=True)

    @dc.app_commands.command(description="Unload bot extension.")
    @dc.app_commands.guild_only()
    # Hide interaction from non-mods
    @dc.app_commands.default_permissions(ban_members=True)
    @dc.app_commands.autocomplete(extension=existing_extension_autocomplete)
    async def unload(self, interaction: dc.Interaction, extension: str) -> None:
        # The client-side check with `default_permissions` isn't guaranteed to work.
        if not self.bot.is_ghostty_mod(interaction.user):
            await interaction.response.send_message(
                "Only mods can use this command.", ephemeral=True
            )
            return
        if not self.bot.is_valid_extension(extension):
            await interaction.response.send_message(
                f"{extension} is an invalid / unknown extension.", ephemeral=True
            )
            return

        await self.bot.unload_extension(extension)
        await interaction.response.send_message(f"Unloaded {extension}", ephemeral=True)

    @dc.app_commands.command(description="Load bot extension.")
    @dc.app_commands.guild_only()
    # Hide interaction from non-mods
    @dc.app_commands.default_permissions(ban_members=True)
    async def load(self, interaction: dc.Interaction, extension: str) -> None:
        # The client-side check with `default_permissions` isn't guaranteed to work.
        if not self.bot.is_ghostty_mod(interaction.user):
            await interaction.response.send_message(
                "Only mods can use this command.", ephemeral=True
            )
            return
        if not self.bot.is_valid_extension(extension):
            await interaction.response.send_message(
                f"{extension} is an invalid / unknown extension.", ephemeral=True
            )
            return

        await self.bot.load_extension(extension)
        await interaction.response.send_message(f"Loaded {extension}", ephemeral=True)

    @load.autocomplete("extension")
    async def unloaded_extensions_autocomplete(
        self, _: dc.Interaction, current: str
    ) -> list[Choice[str]]:
        loaded_extensions = {
            cog_module.__name__
            for cog in self.bot.cogs.values()
            if (cog_module := inspect.getmodule(cog))
        }
        unloaded_cogs_paths = (
            self.bot.get_component_extension_names() - loaded_extensions
        )
        return [
            Choice(name=name, value=name)
            for name in unloaded_cogs_paths
            if current.casefold() in name.casefold()
        ]


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(Developer(bot))
