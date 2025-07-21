from __future__ import annotations

import datetime as dt

import discord as dc

from app import config
from app.utils import aenumerate, dynamic_timestamp, post_is_solved


async def check_for_old_posts(message: dc.Message) -> None:
    post = message.channel
    now = dt.datetime.now(tz=dt.UTC)
    one_minute_ago = now - dt.timedelta(minutes=1)
    one_month_ago = now - dt.timedelta(days=30)

    if (
        not isinstance(post, dc.Thread)
        or not post.parent
        or post.parent.id != config.HELP_CHANNEL_ID
        or post.locked
        or post.last_message_id is None
        or not post_is_solved(post)
        or (
            (starter := post.starter_message) is not None
            # Also check the post starter message, whose timestamp is readily available
            # without fetching messages from Discord. This reduces ratelimits due to
            # a high volume of fetches when messages are sent in the #help channel.
            and starter.created_at > one_month_ago
        )
    ):
        return

    # Ignore messages less than a minute old for the same person may have sent multiple
    # in quick succession, resulting in their own message being considered as activity.
    last = await _get_message(post, 1, before=one_minute_ago)
    # Don't lock the post if it isn't old enough.
    if last is None or last.created_at > one_month_ago:
        # If last was None, there were no messages older than one minute. Assuming the
        # threshold above stays at a reasonably large limit, this either means that
        # every message was deleted, or that there was no response and the original
        # poster deleted the starter message. It's very unlikely for the post to no
        # longer be relevant; nor is it likely that anyone would even message in such
        # a thread. Thus, silently exit if this is the case.
        return

    try:
        creation_time_ago = dynamic_timestamp(
            (await post.fetch_message(post.id)).created_at, "R"
        )
    except dc.NotFound:
        creation_time_ago = "over a month ago"
    await message.reply(
        f"This post was created {creation_time_ago} and is likely no longer relevant. "
        "Please open a new thread instead, making sure to provide the required "
        "information."
    )
    await post.edit(locked=True, archived=True)


async def _get_message(
    thread: dc.Thread,
    n: int,
    *,
    before: dc.abc.SnowflakeTime | None = None,
    around: dc.abc.SnowflakeTime | None = None,
) -> dc.Message | None:
    messages = thread.history(limit=n + 1, before=before, around=around)
    return await anext((m async for i, m in aenumerate(messages) if i == n), None)
