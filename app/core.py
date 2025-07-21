import asyncio
import datetime as dt
import sys
from traceback import print_tb
from typing import cast

import discord as dc
from discord.ext import commands
from sentry_sdk import capture_exception

from app.components.activity_status import randomize_activity_status
from app.components.autoclose import autoclose_solved_posts
from app.components.docs import refresh_sitemap
from app.components.github_integration import (
    ENTITY_REGEX,
    code_link_delete_hook,
    code_link_edit_hook,
    entity_comment_delete_hook,
    entity_comment_edit_hook,
    entity_mention_delete_hook,
    entity_mention_edit_hook,
    load_emojis,
    reply_with_code,
    reply_with_comments,
    reply_with_entities,
)
from app.components.lock_old_posts import check_for_old_posts
from app.components.message_filter import check_message_filters
from app.components.move_message import check_for_edit_response
from app.components.status import bot_status, report_status
from app.components.xkcd_mentions import (
    handle_xkcd_mentions,
    xkcd_mention_delete_hook,
    xkcd_mention_edit_hook,
)
from app.components.zig_codeblocks import (
    check_for_zig_code,
    zig_codeblock_delete_hook,
    zig_codeblock_edit_hook,
)
from app.setup import bot, config
from app.utils import is_dm, is_mod, try_dm


@bot.event
async def on_ready() -> None:
    refresh_sitemap()
    await load_emojis()
    if not autoclose_solved_posts.is_running():
        autoclose_solved_posts.start()
    if not randomize_activity_status.is_running():
        randomize_activity_status.start()
    bot_status.last_login_time = dt.datetime.now(tz=dt.UTC)
    print(f"Bot logged on as {bot.user}!")


@bot.event
async def on_error(*_: object) -> None:
    handle_error(cast("BaseException", sys.exc_info()[1]))


@bot.tree.error
async def on_app_command_error(interaction: dc.Interaction, error: Exception) -> None:
    if not interaction.response.is_done():
        await interaction.response.send_message(
            "Something went wrong :(", ephemeral=True
        )
    handle_error(error)


@bot.event
async def on_message(message: dc.Message) -> None:
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

    coros = [
        check_for_zig_code(message),  # Check for Zig code blocks and format them
        reply_with_code(message),  # Look for GitHub code links and reply with contents
        reply_with_comments(message),  # Check for entity comments and reply with embeds
        check_for_old_posts(message),  # Check for bumps of old help posts and lock them
        handle_xkcd_mentions(message),  # Reply to xkcd mentions with comic embeds
        check_for_edit_response(message),  # Check for responses in active edit threads
    ]

    # Look for issue/PR/discussion mentions and name/link them
    if ENTITY_REGEX.search(message.content):
        coros.append(reply_with_entities(message))

    await asyncio.gather(*coros)


@bot.event
async def on_message_edit(before: dc.Message, after: dc.Message) -> None:
    await asyncio.gather(
        entity_mention_edit_hook(before, after),
        entity_comment_edit_hook(before, after),
        code_link_edit_hook(before, after),
        zig_codeblock_edit_hook(before, after),
        xkcd_mention_edit_hook(before, after),
    )


@bot.event
async def on_message_delete(message: dc.Message) -> None:
    await asyncio.gather(
        entity_mention_delete_hook(message),
        entity_comment_delete_hook(message),
        code_link_delete_hook(message),
        zig_codeblock_delete_hook(message),
        xkcd_mention_delete_hook(message),
    )


async def sync(bot: commands.Bot, message: dc.Message) -> None:
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
    if isinstance(error, dc.app_commands.CommandInvokeError):
        handle_error(error.original)
