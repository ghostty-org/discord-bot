from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, cast

import discord
from discord import app_commands

from app import view
from app.db import models
from app.db.connect import Session
from app.db.utils import fetch_user
from app.setup import bot, config
from app.utils import is_dm, is_mod, is_tester, server_only_warning

if TYPE_CHECKING:
    pass

COOLDOWN_TIME = 604_800  # 1 week


@bot.tree.context_menu(name="Blacklist from vouching")
@discord.app_commands.default_permissions(manage_messages=True)
async def blacklist_vouch_member(
    interaction: discord.Interaction, member: discord.User
) -> None:
    if is_dm(interaction.user):
        await server_only_warning(interaction)
        return

    if not is_mod(interaction.user):
        await interaction.response.send_message(
            "You do not have permission to blacklist users from being vouched for.",
            ephemeral=True,
        )
        return

    db_user = fetch_user(member)

    db_user.is_vouch_blacklisted = not db_user.is_vouch_blacklisted

    with Session(expire_on_commit=False) as session:
        session.add(db_user)
        session.commit()

    await interaction.response.send_message(
        ("B" if db_user.is_vouch_blacklisted else "Unb")
        + f"lacklisted {member.mention}.",
        ephemeral=True,
    )


@bot.tree.command(
    name="blacklist-vouch", description="Blacklist a user from being vouched for."
)
@discord.app_commands.default_permissions(manage_messages=True)
async def blacklist_vouch(
    interaction: discord.Interaction, member: discord.User
) -> None:
    await blacklist_vouch_member.callback(interaction, member)


@bot.tree.context_menu(name="Vouch for Beta")
async def vouch_member(
    interaction: discord.Interaction, member: discord.Member
) -> None:
    """
    Adds a context menu item to a user to vouch for them to join the beta.
    """
    if is_dm(interaction.user):
        await server_only_warning(interaction)
        return

    if not is_tester(interaction.user):
        await interaction.response.send_message(
            "You do not have permission to vouch for new testers.", ephemeral=True
        )
        return

    if member.bot:
        await interaction.response.send_message(
            "Bots can't be vouched for.", ephemeral=True
        )
        return

    if is_tester(member):
        await interaction.response.send_message(
            "This user is already a tester.", ephemeral=True
        )
        return

    db_user = fetch_user(interaction.user)

    if db_user.tester_since is not None and (
        dt.datetime.now(tz=dt.UTC) - db_user.tester_since.replace(tzinfo=dt.UTC)
        < dt.timedelta(weeks=1)
    ):
        await interaction.response.send_message(
            "You have to be a tester for one week in order to vouch.",
            ephemeral=True,
        )
        return

    if _has_vouched_recently(interaction.user) and not is_mod(interaction.user):
        await interaction.response.send_message(
            "You can only vouch once per week.", ephemeral=True
        )
        return

    if _has_already_vouched(interaction.user):
        await interaction.response.send_message(
            "You already have a pending vouch.", ephemeral=True
        )
        return

    if _is_already_vouched_for(member):
        await interaction.response.send_message(
            "This user has already been vouched for.", ephemeral=True
        )
        return

    if fetch_user(interaction.user).is_vouch_blacklisted:
        # We're trolling the user the bot is broken
        await interaction.response.send_message(
            "Something went wrong :(", ephemeral=True
        )
        return

    channel = await bot.fetch_channel(config.MOD_CHANNEL_ID)
    content = (
        f"{interaction.user.mention} vouched for {member.mention} to join the beta."
    )

    with Session(expire_on_commit=False) as session:
        vouch_count = (
            session.query(models.Vouch)
            .filter_by(voucher_id=interaction.user.id)
            .count()
        )

        content += f" (vouch #{vouch_count + 1})"

        db_vouch = models.Vouch(
            voucher_id=interaction.user.id,
            receiver_id=member.id,
        )

        session.add(db_vouch)
        session.commit()

    await cast(discord.TextChannel, channel).send(
        content=content, view=view.DecideVouch(vouch=db_vouch)
    )

    await interaction.response.send_message(
        f"Vouched for {member.mention} as a tester.", ephemeral=True
    )


@vouch_member.error
async def on_vouch_member_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    """
    Handles the rate-limiting for the vouch command.
    """
    if isinstance(error, app_commands.CommandOnCooldown):
        h, m = divmod(int(error.retry_after / 60), 60)
        d, h = divmod(h, 24)
        content = f"Vouches are rate-limited per user. Try again in {d}d {h}h {m}m."
        await interaction.response.send_message(content, ephemeral=True)


@bot.tree.command(name="vouch", description="Vouch for a user to join the beta.")
# @vouch_cooldown
async def vouch(interaction: discord.Interaction, member: discord.User) -> None:
    """
    Same as vouch_member but via a slash command.
    """
    if is_dm(interaction.user):
        await server_only_warning(interaction)
        return
    await vouch_member.callback(interaction, member)


def _is_already_vouched_for(member: discord.Member) -> bool:
    with Session() as session:
        return session.query(models.Vouch).filter_by(receiver_id=member.id).count() > 0


def _has_already_vouched(user: discord.User | discord.Member) -> bool:
    with Session() as session:
        return (
            session.query(models.Vouch)
            .filter_by(voucher_id=user.id)
            .filter_by(vouch_state=models.VouchState.PENDING)
            .count()
            > 0
        )


def _has_vouched_recently(user: discord.User | discord.Member) -> bool:
    one_week_ago = dt.datetime.now(tz=dt.UTC) - dt.timedelta(weeks=1)

    with Session() as session:
        return (
            session.query(models.Vouch)
            .filter_by(voucher_id=user.id)
            .filter(models.Vouch.vouch_state != models.VouchState.PENDING)
            .filter(models.Vouch.request_date > one_week_ago)
            .count()
            > 0
        )
