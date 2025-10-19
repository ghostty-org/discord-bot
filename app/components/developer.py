from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, final

import discord as dc
from discord.ext import commands
from loguru import logger

from app.utils import generate_autocomplete, pretty_print_account

if TYPE_CHECKING:
    from discord.app_commands import Choice

    from app.bot import GhosttyBot


@final
class Developer(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

    async def existing_extension_autocomplete(
        self, _: dc.Interaction, current: str
    ) -> list[Choice[str]]:
        return generate_autocomplete(
            current,
            (
                (name, cog_module.__name__)
                for name, cog in self.bot.cogs.items()
                if (cog_module := inspect.getmodule(cog))
            ),
        )

    @commands.Cog.listener("on_post_message_filter")
    async def sync_handler(self, message: dc.Message) -> None:
        # Handle !sync command. This can't be a slash command because this command is
        # the one that actually adds the slash commands in the first place. This is a
        # fake command because the bot only supports slash commands (special case
        # matching "!sync lateral"
        if message.content.strip() != "!sync":
            return

        if not self.bot.is_ghostty_mod(message.author):
            logger.debug(
                "!sync called by {} who is not a mod",
                pretty_print_account(message.author),
            )
            return

        logger.info("syncing command tree")
        await self.bot.tree.sync()
        await message.reply("Command tree synced.")

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

        if extension:
            if not self.bot.is_valid_extension(extension):
                await interaction.response.send_message(
                    f"Extension `{extension}` does not exist or is invalid.",
                    ephemeral=True,
                )
                return
            extensions = [extension]
        else:
            # If no extension is provided, reload all extensions
            extensions = self.bot.get_component_extension_names()

        reloaded_extensions: list[str] = []
        failed_reloaded_extensions: list[str] = []

        await interaction.response.defer(thinking=True, ephemeral=True)
        for ext in extensions:
            await self.bot.try_unload_extension(ext, user=interaction.user)
            if await self.bot.try_load_extension(ext, user=interaction.user):
                reloaded_extensions.append(ext)
            else:
                failed_reloaded_extensions.append(ext)

        reload_message = ""
        if reloaded_extensions and extension:
            reload_message = f"Reloaded `{extension}`"
        elif reloaded_extensions:
            reload_message = "Reloaded:\n* " + "\n* ".join(
                f"`{e}`" for e in reloaded_extensions
            )
        if failed_reloaded_extensions:
            reload_message += "\nFailed to reload:\n* " + "\n* ".join(
                f"`{e}`" for e in failed_reloaded_extensions
            )
        # Remove the newline if all extensions failed to reload
        reload_message = reload_message.strip()

        await interaction.followup.send(reload_message, ephemeral=True)

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
                f"Extension `{extension}` does not exist or is invalid.", ephemeral=True
            )
            return

        if await self.bot.try_unload_extension(extension, user=interaction.user):
            await interaction.response.send_message(
                f"Unloaded `{extension}`", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Failed to unload `{extension}`", ephemeral=True
            )

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
                f"Extension `{extension}` does not exist or is invalid.", ephemeral=True
            )
            return

        if await self.bot.try_load_extension(extension, user=interaction.user):
            await interaction.response.send_message(
                f"Loaded `{extension}`", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Failed to load `{extension}`", ephemeral=True
            )

    @load.autocomplete("extension")
    async def unloaded_extensions_autocomplete(
        self, _: dc.Interaction, current: str
    ) -> list[Choice[str]]:
        loaded_extensions = {
            cog_module.__name__
            for cog in self.bot.cogs.values()
            if (cog_module := inspect.getmodule(cog))
        }
        unloaded_extension_paths = (
            self.bot.get_component_extension_names() - loaded_extensions
        )
        return generate_autocomplete(current, unloaded_extension_paths)


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(Developer(bot))
