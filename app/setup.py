from __future__ import annotations

import inspect
import logging
import os
import sys
from functools import cached_property
from typing import Any

import discord as dc
from discord.ext import commands
from githubkit import GitHub
from loguru import logger
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def cache_channel[T](field: str, _: type[T]) -> cached_property[T]:
    @cached_property
    def prop(self: Config) -> Any:
        return bot.get_channel(self.model_dump()[field])

    return prop


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BOT_", env_file=".env", enable_decoding=False
    )

    token: str

    github_org: str
    github_repos: dict[str, str]
    github_token: str
    github_webhook_url: str
    github_webhook_secret: str | None = None

    accept_invite_url: str
    sentry_dsn: str | None = None

    help_channel_tag_ids: dict[str, int]

    help_channel_id: int
    log_channel_id: int
    media_channel_id: int
    showcase_channel_id: int
    webhook_channel_id: int

    mod_role_id: int
    helper_role_id: int

    @field_validator("github_repos", mode="before")
    @classmethod
    def parse_repos(cls, value: str) -> dict[str, str]:
        return dict(val.split(":") for val in value.split(","))

    @field_validator("help_channel_tag_ids", mode="before")
    @classmethod
    def parse_tag_ids(cls, value: str) -> dict[str, int]:
        return {
            name: int(id_)
            for name, id_ in (pair.split(":") for pair in value.split(","))
        }

    log_channel = cache_channel("log_channel_id", dc.TextChannel)
    help_channel = cache_channel("help_channel_id", dc.ForumChannel)
    webhook_channel = cache_channel("webhook_channel_id", dc.TextChannel)


if "pytest" in sys.modules:
    Config.model_config["env_file"] = ".env.example"

# https://github.com/pydantic/pydantic-settings/issues/201
config = Config()  # pyright: ignore [reportCallIssue]

intents = dc.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    intents=intents,
    allowed_mentions=dc.AllowedMentions(everyone=False, roles=False),
)

gh = GitHub(config.github_token)


# Both discord.py and httpx use the standard logging module; redirect them to
# Loguru. This code snippet is taken straight from Loguru's README:
# https://github.com/Delgan/loguru/tree/0.7.3#entirely-compatible-with-standard-logging
class _InterceptHandler(logging.Handler):
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


logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

logger.remove()
logger.add(
    sys.stderr,
    # While $LOGURU_LEVEL is checked at import time, it doesn't override this
    # value, so manually handle it.
    level=os.getenv("LOGURU_LEVEL") or os.getenv("LOG_LEVEL") or "INFO",
    filter={
        # httpx logs are very noisy; it logs every single REST request under INFO.
        "httpx": "WARNING",
    },
)
