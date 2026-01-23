import datetime as dt
from typing import TYPE_CHECKING, final, override

import discord as dc
import sentry_sdk
from discord.ext import commands, tasks

from toolbox.discord import post_is_solved

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.bot import GhosttyBot


@final
class AutoClose(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.autoclose_solved_posts.start()

    @override
    async def cog_unload(self) -> None:
        self.autoclose_solved_posts.cancel()
        self.bot.bot_status.help_scan_loop = None

    @tasks.loop(hours=1)
    async def autoclose_solved_posts(self) -> None:
        closed_posts: list[dc.Thread] = []
        failures: list[dc.Thread] = []

        open_posts = len(self.bot.help_channel.threads)
        with sentry_sdk.start_transaction(op="bot.scan", name="all of help_channel"):
            for post in self.bot.help_channel.threads:
                with sentry_sdk.start_span(op="bot.scan", name="post"):
                    if post.archived or not post_is_solved(post):
                        continue
                    if post.last_message_id is None:
                        failures.append(post)
                        continue
                    one_day_ago = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=24)
                    if dc.utils.snowflake_time(post.last_message_id) < one_day_ago:
                        try:
                            await post.edit(archived=True)
                            closed_posts.append(post)
                        except dc.HTTPException:
                            failures.append(post)
                            continue

        self.bot.bot_status.last_scan_results = (
            dt.datetime.now(tz=dt.UTC),
            open_posts,
            len(closed_posts),
        )
        msg = f"Scanned {open_posts:,} open posts in {self.bot.help_channel.mention}.\n"
        if closed_posts:
            msg += f"Automatically closed {self._post_list(closed_posts)}"
        if failures:
            msg += f"Failed to check {self._post_list(failures)}"
        await self.bot.log_channel.send(msg)

    @autoclose_solved_posts.before_loop
    async def before_autoclose_solved_posts(self) -> None:
        await self.bot.wait_until_ready()
        self.bot.bot_status.help_scan_loop = self.autoclose_solved_posts

    @staticmethod
    def _post_list(posts: Sequence[dc.Thread]) -> str:
        return (
            f"{len(posts)} solved posts:\n"
            + "".join(f"* {post.mention}\n" for post in posts[:30])
            + (f"* [...] ({len(posts) - 30:,} more)\n" if len(posts) > 30 else "")
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(AutoClose(bot))
