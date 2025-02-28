import datetime as dt
import sys
from traceback import print_tb
from typing import cast

import discord
from discord.ext import commands
from sentry_sdk import capture_exception

from app.components.autoclose import autoclose_solved_posts
from app.components.docs import refresh_sitemap
from app.components.entity_mentions import (
    ENTITY_REGEX,
    entity_mention_delete_handler,
    entity_mention_edit_handler,
    load_emojis,
    reply_with_entities,
)
from app.components.message_filter import check_message_filters
from app.components.status import bot_status, report_status
from app.components.zig_codeblocks import (
    check_for_zig_code,
    zig_codeblock_delete_handler,
    zig_codeblock_edit_handler,
)
from app.setup import bot, config
from app.utils import is_dm, is_mod, try_dm


@bot.event
async def on_ready() -> None:
    await load_emojis()
    if not autoclose_solved_posts.is_running():
        autoclose_solved_posts.start()
    bot_status.last_login_time = dt.datetime.now(tz=dt.UTC)
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

    # Mod-only commands
    if message.content.rstrip() == "!sync":
        await sync(bot, message)
        return
    if message.content == "status":
        await report_status(message.author)
        return

    # Simple test
    if message.guild is None and message.content == "ping":
        await try_dm(message.author, "pong")
        return

    # Delete invalid messages in #showcase and #media
    if await check_message_filters(message):
        return

    # Look for issue/PR/discussion mentions and name/link them
    if ENTITY_REGEX.search(message.content):
        await reply_with_entities(message)

    # Check for Zig code blocks and format them
    await check_for_zig_code(message)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    await entity_mention_edit_handler(before, after)
    await zig_codeblock_edit_handler(before, after)


@bot.event
async def on_message_delete(message: discord.Message) -> None:
    await entity_mention_delete_handler(message)
    await zig_codeblock_delete_handler(message)


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
