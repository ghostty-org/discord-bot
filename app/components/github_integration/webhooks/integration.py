import asyncio
from typing import TYPE_CHECKING, final, override

import sentry_sdk
from discord.ext import commands
from loguru import logger
from monalisten import Monalisten

from app.components.github_integration.webhooks import commits, discussions, issues, prs
from app.config import config
from app.errors import handle_error

if TYPE_CHECKING:
    from monalisten import AuthIssue, Error

    from app.bot import GhosttyBot


def register_internal_hooks(webhook: Monalisten) -> None:
    @webhook.internal.error
    async def _(error: Error) -> None:
        error.exc.add_note(f"payload: {error.payload}")
        sentry_sdk.set_context("payload", error.payload or {})  # pyright: ignore[reportArgumentType]
        handle_error(error.exc)

    @webhook.internal.auth_issue
    async def _(issue: AuthIssue) -> None:
        guid = issue.payload.get("x-github-delivery", "<missing-guid>")
        logger.warning(
            "token {} in event {}: {}", issue.kind.value, guid, issue.payload
        )

    @webhook.internal.ready
    async def _() -> None:
        logger.info("monalisten client ready")


@final
class GitHubWebhooks(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.monalisten_client = Monalisten(
            config.github_webhook_url.get_secret_value(),
            token=config.github_webhook_secret.get_secret_value()
            if config.github_webhook_secret
            else None,
        )
        self._monalisten_task: asyncio.Task[None] | None = None

    @override
    async def cog_load(self) -> None:
        register_internal_hooks(self.monalisten_client)
        discussions.register_hooks(self.bot, self.monalisten_client)
        issues.register_hooks(self.bot, self.monalisten_client)
        prs.register_hooks(self.bot, self.monalisten_client)
        commits.register_hooks(self.bot, self.monalisten_client)

        # Maintain strong reference to avoid task from being gc
        self._monalisten_task = asyncio.create_task(self.monalisten_client.listen())

    @override
    async def cog_unload(self) -> None:
        if self._monalisten_task and not self._monalisten_task.done():
            self._monalisten_task.cancel()


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(GitHubWebhooks(bot))
