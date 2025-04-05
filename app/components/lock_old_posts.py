from __future__ import annotations

import datetime as dt

import discord

from app import config
from app.utils import dynamic_timestamp, post_is_solved


async def check_for_old_posts(message: discord.Message) -> None:
    post = message.channel
    now = dt.datetime.now(tz=dt.UTC)
    if (
        not isinstance(post, discord.Thread)
        or not post.parent
        or post.parent.id != config.HELP_CHANNEL_ID
        or post.locked
        or post.last_message_id is None
        or not post_is_solved(post)
    ):
        return
    try:
        # Ignore messages less than a minute old for the same person may have
        # sent multiple in quick succession, resulting in their own message
        # being considered as activity.
        last = await _get_message(post, 1, before=now - dt.timedelta(minutes=1))
    except IndexError:
        # There were no messages older than one minute. Assuming the treshold
        # below stays at a reasonably large limit, this either means that every
        # message was deleted, or that there was no response and the original
        # poster deleted the starter message. It's very unlikely for the post
        # tono longer be relevant; nor is it likely that anyone would even
        # message in such a thread. Thus, silently exit if this is the case.
        return
    if last.created_at > now - dt.timedelta(seconds=30):
        return

    try:
        creation_time_ago = dynamic_timestamp(
            (await post.fetch_message(post.id)).created_at, "R"
        )
    except discord.NotFound:
        creation_time_ago = "over a month ago"
    await message.reply(
        f"This post was created {creation_time_ago} and is likely no longer "
        "relevant. Please open a new thread instead, making sure to provide "
        "the required information."
    )
    await post.edit(locked=True)


async def _get_message(
    thread: discord.Thread,
    n: int,
    *,
    before: discord.abc.SnowflakeTime | None = None,
    around: discord.abc.SnowflakeTime | None = None,
) -> discord.Message:
    return [
        message
        async for message in thread.history(limit=n + 1, before=before, around=around)
    ][n]
