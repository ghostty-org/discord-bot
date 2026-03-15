import asyncio
from contextlib import suppress

from loguru import logger

from app.bot import GhosttyBot
from app.config import config


async def main() -> None:
    async with GhosttyBot() as bot:
        logger.debug("starting the bot")
        await bot.start(config().token.get_secret_value())


with suppress(KeyboardInterrupt):
    asyncio.run(main())
