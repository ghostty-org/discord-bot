from __future__ import annotations

import asyncio
import datetime as dt
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast, final

from githubkit import TokenAuthStrategy
from githubkit.exception import RequestFailed

from app.config import config, gh
from app.utils import dynamic_timestamp

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import discord as dc
    from discord.ext import tasks

    from app.common.hooks import ProcessedMessage

STATUS_MESSAGE_TEMPLATE = """
### Commit
{commit}
### Uptime
* Launch time: {launch_time}
* Last login time: {last_login_time}
### {help_channel} post scan status
* Last scan: {scan.scanned} scanned, {scan.closed} closed ({scan.time_since})
* Next scan: {scan.time_until_next}
### GitHub status
* Auth: {gh.auth}
* API: {gh.api}
### Sitemap
* Last refresh: {last_sitemap_refresh}
"""


@final
class BotStatus:
    launch_time: dt.datetime
    help_scan_loop: tasks.Loop[Any] | None = None
    last_login_time: dt.datetime | None = None
    last_scan_results: tuple[dt.datetime, int, int] | None = None
    last_sitemap_refresh: dt.datetime | None = None
    commit_links: Callable[[dc.Message], Awaitable[ProcessedMessage]] | None = None

    def __init__(self) -> None:
        self.launch_time = dt.datetime.now(tz=dt.UTC)
        self._commit = None

    @property
    def initialized(self) -> bool:
        return all((
            self.last_login_time,
            self.last_sitemap_refresh,
            self.last_scan_results,
        ))

    def _get_scan_data(self) -> SimpleNamespace:
        if not self.help_scan_loop:
            return SimpleNamespace(
                time_since="**disabled**",
                time_until_next="**disabled**",
                scanned=0,
                closed=0,
            )

        next_scan = cast("dt.datetime", self.help_scan_loop.next_iteration)
        assert self.last_scan_results is not None
        last_scan, scanned, closed = self.last_scan_results
        return SimpleNamespace(
            time_since=dynamic_timestamp(last_scan, "R"),
            time_until_next=dynamic_timestamp(next_scan, "R"),
            scanned=scanned,
            closed=closed,
        )

    @staticmethod
    async def _get_github_data() -> tuple[bool, SimpleNamespace]:
        match gh.auth:
            case TokenAuthStrategy(token) if token.startswith(("gh", "github")):
                correct_token = True
            case _:
                correct_token = False
        try:
            resp = await gh.rest.users.async_get_authenticated()
            api_ok = resp.status_code == 200
        except RequestFailed:
            api_ok = False
        return correct_token and api_ok, SimpleNamespace(
            auth="✅" if correct_token else "❌",
            api="✅" if api_ok else "❌",
        )

    async def _get_commit(self, *, github_functional: bool = False) -> str:
        if self._commit:
            # Use cached commit.
            return self._commit
        git_proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD", stdout=subprocess.PIPE
        )
        assert git_proc.stdout is not None  # set to PIPE above
        if await git_proc.wait() != 0 or not (
            commit_hash := (await git_proc.stdout.read()).decode().strip()
        ):
            self._commit = "Unknown"
            return self._commit
        commit_url = f"https://github.com/ghostty-org/discord-bot/commit/{commit_hash}"
        if github_functional and self.commit_links:
            output = await self.commit_links(
                # Forging a message to use the commit links logic
                cast("dc.Message", SimpleNamespace(content=commit_url))
            )
            if output.item_count:
                self._commit = output.content
                return self._commit
        self._commit = f"[`{commit_hash}`](<{commit_url}>)"
        return self._commit

    async def export(self) -> dict[str, str | SimpleNamespace]:
        """
        Make sure the bot has finished initializing before calling this, using the
        `initialized` property.
        """
        assert self.last_login_time is not None
        assert self.last_sitemap_refresh is not None
        github_functional, github_data = await self._get_github_data()
        return {
            "commit": await self._get_commit(github_functional=github_functional),
            "launch_time": dynamic_timestamp(self.launch_time, "R"),
            "last_login_time": dynamic_timestamp(self.last_login_time, "R"),
            "last_sitemap_refresh": dynamic_timestamp(self.last_sitemap_refresh, "R"),
            "help_channel": f"<#{config.help_channel_id}>",
            "scan": self._get_scan_data(),
            "gh": github_data,
        }

    async def status_message(self) -> str:
        if not self.initialized:
            return "The bot has not finished initializing yet; try again shortly."
        return STATUS_MESSAGE_TEMPLATE.format(**(await self.export()))
