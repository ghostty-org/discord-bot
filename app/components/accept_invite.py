from typing import TYPE_CHECKING, final

import discord as dc
from discord.ext import commands
from loguru import logger

from app.config import config
from toolbox.discord import is_dm, pretty_print_account, try_dm

if TYPE_CHECKING:
    from app.bot import GhosttyBot


@final
class AcceptInvite(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

    @dc.app_commands.command(
        name="accept-invite", description="Accept a pending tester invite."
    )
    @dc.app_commands.guild_only()
    async def accept_invite(self, interaction: dc.Interaction) -> None:
        assert not is_dm(interaction.user)

        await try_dm(interaction.user, config().accept_invite_url, silent=True)
        await try_dm(
            interaction.user,
            "Ghostty is already out! 👉 https://ghostty.org/",
        )
        await interaction.response.send_message("Check your DMs!", ephemeral=True)

        logger.debug("{} accepted the invite", pretty_print_account(interaction.user))
        await self.bot.log_channel.send(
            f"{interaction.user.mention} accepted the invite!",
            allowed_mentions=dc.AllowedMentions.none(),
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(AcceptInvite(bot))
