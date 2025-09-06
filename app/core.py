import asyncio
import datetime as dt

import discord as dc
from discord.ext import commands
from loguru import logger

from app.components.activity_status import randomize_activity_status
from app.components.autoclose import autoclose_solved_posts
from app.components.docs import refresh_sitemap
from app.components.github_integration import (
    ENTITY_REGEX,
    code_link_delete_hook,
    code_link_edit_hook,
    commit_mention_delete_hook,
    commit_mention_edit_hook,
    entity_comment_delete_hook,
    entity_comment_edit_hook,
    entity_mention_delete_hook,
    entity_mention_edit_hook,
    load_emojis,
    reply_with_code,
    reply_with_comments,
    reply_with_commit_details,
    reply_with_entities,
)
from app.components.github_integration.mentions.integration import (
    update_recent_mentions,
)
from app.components.github_integration.webhooks import monalisten_client
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
from app.errors import handle_task_error
from app.setup import bot
from app.utils import is_dm, is_mod, try_dm

TASKS = (autoclose_solved_posts, randomize_activity_status, update_recent_mentions)
background_tasks = set[asyncio.Task[None]]()


@bot.event
async def on_ready() -> None:
    refresh_sitemap()
    await load_emojis()
    for task in TASKS:
        if not task.is_running():
            task.start()

    # Creating a strong reference
    monalisten_task = asyncio.create_task(monalisten_client.listen())
    monalisten_task.add_done_callback(handle_task_error)
    background_tasks.add(monalisten_task)

    bot_status.last_login_time = dt.datetime.now(tz=dt.UTC)
    logger.info("logged in as {}", bot.user)


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
        reply_with_commit_details(message),  # Reply to commit SHAs with GitHub links
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
        commit_mention_edit_hook(before, after),
    )


@bot.event
async def on_message_delete(message: dc.Message) -> None:
    await asyncio.gather(
        entity_mention_delete_hook(message),
        entity_comment_delete_hook(message),
        code_link_delete_hook(message),
        zig_codeblock_delete_hook(message),
        xkcd_mention_delete_hook(message),
        commit_mention_delete_hook(message),
    )


async def sync(bot: commands.Bot, message: dc.Message) -> None:
    """Syncs all global commands."""
    if is_dm(message.author) or not is_mod(message.author):
        return

    refresh_sitemap()
    await bot.tree.sync()
    await try_dm(message.author, "Command tree synced.")
