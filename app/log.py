import inspect
import logging
import os
import sys
from typing import TYPE_CHECKING, override

import sentry_sdk
from loguru import logger
from sentry_sdk.integrations.asyncio import AsyncioIntegration

if TYPE_CHECKING:
    from app.config import Config


# Both discord.py and httpx use the standard logging module; redirect them to Loguru.
# This code snippet is taken straight from Loguru's README:
# https://github.com/Delgan/loguru/tree/0.7.3#entirely-compatible-with-standard-logging
class _InterceptHandler(logging.Handler):
    @override
    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists.
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup(config: Config) -> None:
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    logger.remove()
    logger.add(
        sys.stderr,
        # While $LOGURU_LEVEL is checked at import time, it doesn't override this value,
        # so manually handle it.
        level=os.getenv("LOGURU_LEVEL") or os.getenv("LOG_LEVEL") or "INFO",
        filter={
            # httpx logs are quite noisy: it logs every single REST request under INFO.
            "httpx": "WARNING",
        },
    )

    if config.sentry_dsn is not None:
        logger.info("initializing sentry")
        sentry_sdk.init(
            dsn=config.sentry_dsn.get_secret_value(),
            enable_logs=True,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            profile_lifecycle="trace",
            integrations=[AsyncioIntegration()],
        )
