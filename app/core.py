import sys
from traceback import print_tb
from typing import cast

import discord
from discord.ext import commands
from sentry_sdk import capture_exception

from app.components.autoclose import autoclose_solved_posts
from app.components.docs import refresh_sitemap
from app.components.entity_mentions import (
    has_entity_mention,
    load_emojis,
    reply_with_entities,
)
from app.components.message_filter import check_message_filters
from app.setup import bot, config
from app.utils import is_dm, is_mod, try_dm


@bot.event
async def on_ready() -> None:
    await load_emojis()
    autoclose_solved_posts.start()
    print(f"Bot logged on as {bot.user}!")


@bot.event
async def on_error(*_: object) -> None:
    handle_error(cast(BaseException, sys.exc_info()[1]))


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: Exception
) -> None:
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "Something went wrong :(", ephemeral=True
        )
    handle_error(error)


@bot.event
async def on_message(message: discord.Message) -> None:
    # Ignore our own messages
    if message.author == bot.user:
        return

    # Mod-only sync command
    if message.content.rstrip() == "!sync":
        await sync(bot, message)
        return

    # Simple test
    if message.guild is None and message.content == "ping":
        await try_dm(message.author, "pong")
        return

    # Delete invalid messages in #showcase and #media
    if await check_message_filters(message):
        return

    # Look for issue/PR/discussion mentions and name/link them
    if has_entity_mention(message.content):
        await reply_with_entities(message)


async def sync(bot: commands.Bot, message: discord.Message) -> None:
    """Syncs all global commands."""
    if is_dm(message.author) or not is_mod(message.author):
        return

    refresh_sitemap()
    await bot.tree.sync()
    await try_dm(message.author, "Command tree synced.")


def handle_error(error: BaseException) -> None:
    if config.SENTRY_DSN is not None:
        capture_exception(error)
        return

    print(type(error).__name__, "->", error)
    print_tb(error.__traceback__)
    if isinstance(error, discord.app_commands.CommandInvokeError):
        handle_error(error.original)
