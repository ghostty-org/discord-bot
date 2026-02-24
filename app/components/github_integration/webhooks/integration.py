# pyright: reportUnusedFunction=false

import asyncio
from typing import TYPE_CHECKING, final, override

import sentry_sdk
from discord.ext import commands
from loguru import logger
from monalisten import Monalisten

from app.components.github_integration.webhooks import commits, discussions, issues, prs
from app.config import config
from toolbox.errors import handle_error

if TYPE_CHECKING:
    from monalisten import AuthIssue, Error

    from app.bot import GhosttyBot
    from app.components.github_integration.webhooks.vouch import VouchQueue


def register_internal_hooks(webhook: Monalisten) -> None:
    @webhook.internal.error
    async def error(error: Error) -> None:
        error.exc.add_note(f"payload: {error.payload}")
        sentry_sdk.set_context("payload", error.payload or {})  # pyright: ignore[reportArgumentType]
        handle_error(error.exc)

    @webhook.internal.auth_issue
    async def auth_issue(issue: AuthIssue) -> None:
        guid = issue.payload.get("x-github-delivery", "<missing-guid>")
        logger.warning(
            "token {} in event {}: {}", issue.kind.value, guid, issue.payload
        )

    @webhook.internal.ready
    async def ready() -> None:
        logger.info("monalisten client ready")


@final
class GitHubWebhooks(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.monalisten_client = Monalisten(
            config().github_webhook_url.get_secret_value(),
            token=token.get_secret_value()
            if (token := config().github_webhook_secret)
            else None,
        )
        self._monalisten_task: asyncio.Task[None] | None = None
        self._vouch_queue: VouchQueue = {}

    @override
    async def cog_load(self) -> None:
        register_internal_hooks(self.monalisten_client)
        discussions.register_hooks(self.bot, self.monalisten_client, self._vouch_queue)
        issues.register_hooks(self.bot, self.monalisten_client, self._vouch_queue)
        prs.register_hooks(self.bot, self.monalisten_client, self._vouch_queue)
        commits.register_hooks(self.bot, self.monalisten_client)

        # Maintain strong reference to avoid task from being gc
        self._monalisten_task = asyncio.create_task(self.monalisten_client.listen())

    @override
    async def cog_unload(self) -> None:
        if self._monalisten_task and not self._monalisten_task.done():
            self._monalisten_task.cancel()


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(GitHubWebhooks(bot))
