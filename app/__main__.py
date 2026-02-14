import asyncio
from contextlib import suppress

from githubkit import GitHub
from loguru import logger

from app import log
from app.bot import GhosttyBot
from app.config import Config, config, gh


async def main() -> None:
    app_config = Config(".env")
    gh_client = GitHub(app_config.github_token.get_secret_value())
    with config.set(app_config), gh.set(gh_client):
        log.setup()
        logger.trace("creating GhosttyBot instance for starting bot")
        async with GhosttyBot() as bot:
            logger.debug("starting the bot")
            await bot.start(config.get().token.get_secret_value())


with suppress(KeyboardInterrupt):
    asyncio.run(main())
