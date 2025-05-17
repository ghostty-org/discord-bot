import datetime as dt
import subprocess
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

from githubkit import TokenAuthStrategy
from githubkit.exception import RequestFailed

from app.setup import bot, config, gh
from app.utils import Account, dynamic_timestamp, is_dm, is_mod, try_dm

STATUS_MESSAGE_TEMPLATE = """
### Commit
{commit_hash}
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


def get_github_data() -> SimpleNamespace:
    match gh.auth:
        case TokenAuthStrategy(token) if token.startswith(("gh", "github")):
            correct_token = True
        case _:
            correct_token = False
    try:
        resp = gh.rest.users.get_authenticated()
        api_ok = resp.status_code == 200
    except RequestFailed:
        api_ok = False
    return SimpleNamespace(
        auth="✅" if correct_token else "❌",
        api="✅" if api_ok else "❌",
    )


@dataclass
class BotStatus:
    launch_time: dt.datetime
    last_login_time: dt.datetime | None = None
    last_scan_results: tuple[dt.datetime, int, int] | None = None
    last_sitemap_refresh: dt.datetime | None = None

    @property
    def initialized(self) -> bool:
        return all(
            (self.last_login_time, self.last_sitemap_refresh, self.last_scan_results)
        )

    def _get_scan_data(self) -> SimpleNamespace:
        # Avoid circular import
        from app.components.autoclose import autoclose_solved_posts

        next_scan = cast("dt.datetime", autoclose_solved_posts.next_iteration)

        assert self.last_scan_results is not None
        last_scan, scanned, closed = self.last_scan_results
        return SimpleNamespace(
            time_since=dynamic_timestamp(last_scan, "R"),
            time_until_next=dynamic_timestamp(next_scan, "R"),
            scanned=scanned,
            closed=closed,
        )

    def export(self) -> dict[str, str | SimpleNamespace]:
        """
        Make sure the bot has finished initializing before calling this, using
        the `initialized` property.
        """
        assert self.last_login_time is not None
        assert self.last_sitemap_refresh is not None
        return {
            "launch_time": dynamic_timestamp(self.launch_time, "R"),
            "last_login_time": dynamic_timestamp(self.last_login_time, "R"),
            "last_sitemap_refresh": dynamic_timestamp(self.last_sitemap_refresh, "R"),
            "help_channel": f"<#{config.HELP_CHANNEL_ID}>",
            "scan": self._get_scan_data(),
            "gh": get_github_data(),
        }


bot_status = BotStatus(dt.datetime.now(tz=dt.UTC))


def _get_commit_hash() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"])
            .decode()
            .strip()
            .join("``")
        )
    except subprocess.CalledProcessError:
        return "Unknown"


def status_message() -> str:
    if not bot_status.initialized:
        return "The bot has not finished initializing yet; try again shortly."
    return STATUS_MESSAGE_TEMPLATE.format(
        commit_hash=_get_commit_hash(),
        **bot_status.export(),
    )


async def report_status(user: Account) -> None:
    if not is_dm(user):
        return
    member = bot.guilds[0].get_member(user.id)
    if member is None or not is_mod(member):
        return
    await try_dm(user, status_message())
