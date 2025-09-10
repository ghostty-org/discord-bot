import asyncio
from contextlib import suppress

from loguru import logger

from app import log
from app.bot import GhosttyBot
from app.config import config, gh


async def main() -> None:
    log.setup(config)

    logger.trace("creating a GhosttyBot instance for starting")
    async with GhosttyBot(config, gh) as bot:
        logger.debug("starting the bot")
        await bot.start(config.token.get_secret_value())


with suppress(KeyboardInterrupt):
    asyncio.run(main())
