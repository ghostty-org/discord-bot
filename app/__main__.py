import asyncio
from contextlib import suppress

from loguru import logger

from app import log
from app.bot import GhosttyBot
from app.config import Config


async def main() -> None:
    # https://github.com/pydantic/pydantic-settings/issues/201
    config = Config()  # pyright: ignore[reportCallIssue]

    log.setup(config)

    logger.trace("creating GhosttyBot instance for starting bot")
    async with GhosttyBot(config) as bot:
        logger.debug("starting the bot")
        await bot.start(config.token.get_secret_value())


with suppress(KeyboardInterrupt):
    asyncio.run(main())
