import asyncio
from contextlib import suppress

from githubkit import GitHub
from loguru import logger

from app import log
from app.bot import GhosttyBot
from app.config import Config, config, config_var, gh_var


async def main() -> None:
    with (
        config_var.set(Config(".env")),
        gh_var.set(GitHub(config().github_token.get_secret_value())),
    ):
        log.setup()
        logger.trace("creating GhosttyBot instance for starting bot")
        async with GhosttyBot() as bot:
            logger.debug("starting the bot")
            await bot.start(config().token.get_secret_value())


with suppress(KeyboardInterrupt):
    asyncio.run(main())
