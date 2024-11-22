from typing import cast

import discord

from app import view
from app.setup import bot, config
from app.utils import (
    SERVER_ONLY,
    Account,
    has_linked_github,
    is_dm,
    is_mod,
    is_tester,
    try_dm,
)


async def log_invite(
    inviter: Account,
    invitee: discord.Member,
    *,
    note: str = "",
) -> None:
    channel = cast(
        discord.TextChannel, await bot.fetch_channel(config.INVITELOG_CHANNEL_ID)
    )
    content = f"{inviter.mention} invited {invitee.mention} to the beta"
    if note:
        content += f" ({note})"
    await channel.send(content, allowed_mentions=discord.AllowedMentions.none())


@bot.tree.context_menu(name="Invite to Beta")
@discord.app_commands.default_permissions(manage_messages=True)
@SERVER_ONLY
async def invite_member(
    interaction: discord.Interaction, member: discord.Member
) -> None:
    """
    Adds a context menu item to a user to invite them to the beta.

    This can only be invoked by a mod.
    """
    assert not is_dm(interaction.user)

    await interaction.response.defer(thinking=True, ephemeral=True)

    if not is_mod(interaction.user):
        await interaction.followup.send(
            "You do not have permission to invite new testers.", ephemeral=True
        )
        return

    if member.bot:
        await interaction.followup.send("Bots can't be testers.", ephemeral=True)
        return

    if is_tester(member):
        await interaction.followup.send(
            "This user is already a tester.", ephemeral=True
        )
        return

    await member.add_roles(
        discord.Object(config.TESTER_ROLE_ID),
        reason="invite to beta context menu",
    )
    await try_dm(member, view.NEW_TESTER_DM)

    await interaction.followup.send(f"Added {member} as a tester.", ephemeral=True)
    await log_invite(interaction.user, member)


@bot.tree.command(name="invite", description="Invite a user to the beta.")
@discord.app_commands.default_permissions(manage_messages=True)
@SERVER_ONLY
async def invite(interaction: discord.Interaction, member: discord.Member) -> None:
    """Same as invite_member but via a slash command."""
    await invite_member.callback(interaction, member)


@bot.tree.command(name="accept-invite", description="Accept a pending tester invite.")
@SERVER_ONLY
async def accept_invite(interaction: discord.Interaction) -> None:
    """
    Accept the tester invite. This should be invoked by someone who was
    invited to the beta to complete setup with GitHub.
    """
    assert not is_dm(interaction.user)

    if not is_tester(interaction.user):
        await interaction.response.send_message(
            "You haven't been invited to be a tester yet.", ephemeral=True
        )
        return

    if has_linked_github(interaction.user):
        await interaction.response.send_message(
            view.TESTER_LINK_ALREADY, ephemeral=True
        )
        return

    # Send the tester link view
    await interaction.response.send_message(
        view.TESTER_ACCEPT_INVITE, view=view.TesterWelcome(), ephemeral=True
    )
