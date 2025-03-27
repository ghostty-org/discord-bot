import datetime as dt

import discord

from app import config
from app.utils import dynamic_timestamp, post_is_solved


async def check_for_old_posts(message: discord.Message) -> None:
    post = message.channel
    now = dt.datetime.now(tz=dt.UTC)
    two_fortnights_ago = now - dt.timedelta(weeks=4)
    one_minute_ago = now - dt.timedelta(minutes=1)
    if (
        not isinstance(post, discord.Thread)
        or not post.parent
        or post.parent.id != config.HELP_CHANNEL_ID
        or post.locked
        or post.last_message_id is None
        or not post_is_solved(post)
        or (await _get_message(post, 1, before=one_minute_ago)).created_at
        > two_fortnights_ago
    ):
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
    /,
    *,
    before: discord.abc.Snowflake | dt.datetime | None = None,
    around: discord.abc.Snowflake | dt.datetime | None = None,
    strict: bool = False,
) -> discord.Message:
    messages = [
        message
        async for message in thread.history(limit=n + 1, before=before, around=around)
    ]
    if messages or strict:
        return messages[n]
    return [message async for message in thread.history(limit=n + 1)][n]
