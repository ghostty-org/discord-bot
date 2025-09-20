from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import sentry_sdk
from loguru import logger
from monalisten import Monalisten

from app.components.github_integration.webhooks.commits import Commits
from app.components.github_integration.webhooks.discussions import Discussions
from app.components.github_integration.webhooks.issues import Issues
from app.components.github_integration.webhooks.prs import PRs
from app.config import config
from app.errors import handle_error, handle_task_error

if TYPE_CHECKING:
    from monalisten import AuthIssue, Error

    from app.bot import GhosttyBot


def register_hooks(webhook: Monalisten) -> None:
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


async def setup(bot: GhosttyBot) -> None:
    monalisten_client = Monalisten(
        config.github_webhook_url.get_secret_value(),
        token=config.github_webhook_secret.get_secret_value()
        if config.github_webhook_secret
        else None,
    )
    register_hooks(monalisten_client)

    await bot.add_cog(Commits(bot, monalisten_client))
    await bot.add_cog(Discussions(bot, monalisten_client))
    await bot.add_cog(Issues(bot, monalisten_client))
    await bot.add_cog(PRs(bot, monalisten_client))

    monalisten_task = asyncio.create_task(monalisten_client.listen())
    monalisten_task.add_done_callback(handle_task_error)
    bot.background_tasks.add(monalisten_task)
