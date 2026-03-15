import asyncio
import datetime as dt
import importlib
import importlib.util
import pkgutil
import sys
from contextvars import ContextVar
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast, final, get_args, override

import discord as dc
import sentry_sdk
from discord.ext import commands
from githubkit import GitHub
from loguru import logger

from app import log
from app.config import Config, config, config_var, gh_var
from app.status import BotStatus
from toolbox.discord import pretty_print_account, try_dm
from toolbox.errors import handle_error, interaction_error_handler
from toolbox.messages import REGULAR_MESSAGE_TYPES

if TYPE_CHECKING:
    from toolbox.discord import Account

EmojiName = Literal[
    "commit",
    "discussion",
    "discussion_answered",
    "discussion_duplicate",
    "discussion_outdated",
    "issue_closed_completed",
    "issue_closed_unplanned",
    "issue_open",
    "pull_closed",
    "pull_draft",
    "pull_merged",
    "pull_open",
]

_EMOJI_NAMES = frozenset(get_args(EmojiName))

emojis_var = ContextVar[MappingProxyType[EmojiName, dc.Emoji | Literal["❓"]]](
    "emojis", default=MappingProxyType(dict.fromkeys(_EMOJI_NAMES, "❓"))
)
emojis = emojis_var.get


@final
class GhosttyBot(commands.Bot):
    def __init__(self) -> None:
        log.setup()
        self._config_context_token = config_var.set(Config(".env", bot=self))
        log.setup_sentry(config().sentry_dsn)
        self._gh_context_token = gh_var.set(
            GitHub(config().github_token.get_secret_value())
        )

        intents = dc.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=[],
            intents=intents,
            allowed_mentions=dc.AllowedMentions(everyone=False, roles=False),
        )

        self.tree.on_error = interaction_error_handler
        self.bot_status = BotStatus()

        # Retain the default: this dict will later be mutated by load_emojis, and if
        # a cog accesses emojis before load_emojis finishes it'll throw a KeyError.
        self._emojis = dict(emojis_var.get())
        # Contexts, within which ContextVars are stored, are thread-local; setting
        # emojis_var in load_emojis doesn't work as they're set in a different Context,
        # which asyncio never has a chance to copy into other coroutines' Contexts.
        # Thus, set the variable here and mutate its value in load_emojis.
        self._emojis_context_token = emojis_var.set(MappingProxyType(self._emojis))
        self.emojis_loaded = asyncio.Event()

    @override
    async def close(self) -> None:
        config_var.reset(self._config_context_token)
        gh_var.reset(self._gh_context_token)
        emojis_var.reset(self._emojis_context_token)

    @override
    async def on_error(self, event_method: str, /, *args: Any, **kwargs: Any) -> None:
        handle_error(cast("BaseException", sys.exception()))

    @override
    async def load_extension(self, name: str, *, package: str | None = None) -> None:
        short_name = name.removeprefix("app.components.")
        logger.debug("loading extension {}", short_name)
        with sentry_sdk.start_span(op="bot.load_extension", name=short_name):
            await super().load_extension(name, package=package)

    async def _try_extension(
        self,
        operation: Literal["load", "unload"],
        name: str,
        *,
        package: str | None = None,
        user: Account | None = None,
    ) -> bool:
        extension_operation = (
            self.load_extension if operation == "load" else self.unload_extension
        )
        try:
            await extension_operation(name, package=package)
        except commands.ExtensionFailed as error:
            logger.opt(exception=error).exception(
                (f"{pretty_print_account(user)} " if user else "")
                + f"failed to {operation} `{name}`"
            )
        except commands.ExtensionError as error:
            message = (
                f"{user} " if user else ""
            ) + f"failed to {operation} `{name}`: {error}"
            logger.warning(message)
        else:
            return True
        return False

    async def try_load_extension(
        self, name: str, *, package: str | None = None, user: Account | None = None
    ) -> bool:
        return await self._try_extension("load", name, package=package, user=user)

    async def try_unload_extension(
        self, name: str, *, package: str | None = None, user: Account | None = None
    ) -> bool:
        return await self._try_extension("unload", name, package=package, user=user)

    @override
    async def setup_hook(self) -> None:
        with sentry_sdk.start_transaction(op="bot.setup", name="Initial load"):
            await self.bot_status.load_git_data()
            async with asyncio.TaskGroup() as group:
                for extension in self.get_component_extension_names():
                    group.create_task(self.load_extension(extension))
        logger.info("loaded {} extensions", len(self.extensions))

    async def on_ready(self) -> None:
        self.bot_status.last_login_time = dt.datetime.now(tz=dt.UTC)
        await self.load_emojis()
        logger.info("logged in as {}", self.user)

    def _fails_message_filters(self, message: dc.Message) -> bool:
        # This can't be the MessageFilter cog type because that would cause an import
        # cycle.
        message_filter: Any = self.get_cog("MessageFilter")
        return bool(message_filter and message_filter.check(message))

    @override
    async def on_message(self, message: dc.Message, /) -> None:
        if message.author.bot or message.type not in REGULAR_MESSAGE_TYPES:
            return

        # Simple test
        if message.guild is None and message.content == "ping":
            logger.debug("ping sent by {}", pretty_print_account(message.author))
            await try_dm(message.author, "pong")
            return

        if not self._fails_message_filters(message):
            self.dispatch("message_filter_passed", message)

    @classmethod
    def get_component_extension_names(cls) -> frozenset[str]:
        modules: set[str] = set()
        for module_info in pkgutil.walk_packages(
            [Path(__file__).parent / "components"], "app.components."
        ):
            if cls.is_valid_extension(module_info.name):
                modules.add(module_info.name)

        return frozenset(modules)

    @staticmethod
    def is_valid_extension(extension: str) -> bool:
        return (
            extension.startswith("app.components.")
            and bool(importlib.util.find_spec(extension))
            and callable(getattr(importlib.import_module(extension), "setup", None))
        )

    async def load_emojis(self) -> None:
        self.emojis_loaded.clear()

        for emoji in config().ghostty_guild.emojis:
            if emoji.name in _EMOJI_NAMES:
                self._emojis[cast("EmojiName", emoji.name)] = emoji

        if missing_emojis := _EMOJI_NAMES - {
            k for k, v in self._emojis.items() if v != "❓"
        }:
            emoji_list = ", ".join(missing_emojis)
            logger.error("failed to load emojis {}", emoji_list)
            await config().log_channel.send(
                f"Failed to load the following emojis: {emoji_list}"
            )

        self.emojis_loaded.set()
