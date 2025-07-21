import datetime as dt
from collections.abc import Sequence
from typing import cast

import discord as dc
from discord.ext import tasks

from app.components.status import bot_status
from app.setup import bot, config
from app.utils import post_is_solved


@tasks.loop(hours=1)
async def autoclose_solved_posts() -> None:
    closed_posts: list[dc.Thread] = []
    failures: list[dc.Thread] = []

    help_channel = cast("dc.ForumChannel", bot.get_channel(config.HELP_CHANNEL_ID))
    open_posts = len(help_channel.threads)
    for post in help_channel.threads:
        if post.archived or not post_is_solved(post):
            continue
        if post.last_message_id is None:
            failures.append(post)
            continue
        one_day_ago = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24)
        if dc.utils.snowflake_time(post.last_message_id) < one_day_ago:
            await post.edit(archived=True)
            closed_posts.append(post)

    log_channel = cast("dc.TextChannel", bot.get_channel(config.LOG_CHANNEL_ID))
    bot_status.last_scan_results = (
        dt.datetime.now(tz=dt.UTC),
        open_posts,
        len(closed_posts),
    )
    msg = f"Scanned {open_posts:,} open posts in {help_channel.mention}.\n"
    if closed_posts:
        msg += f"Automatically closed {_post_list(closed_posts)}"
    if failures:
        msg += f"Failed to check {_post_list(failures)}"
    await log_channel.send(msg)


def _post_list(posts: Sequence[dc.Thread]) -> str:
    return (
        f"{len(posts)} solved posts:\n"
        + "".join(f"* {post.mention}\n" for post in posts[:30])
        + (f"* [...] ({len(posts) - 30:,} more)\n" if len(posts) > 30 else "")
    )
