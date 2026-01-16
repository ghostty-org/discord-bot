import asyncio
import datetime as dt
import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast, final, get_args, override

import discord as dc
import sentry_sdk
from discord.ext import commands
from loguru import logger

from app.status import BotStatus
from toolbox.errors import handle_error, interaction_error_handler
from toolbox.misc import REGULAR_MESSAGE_TYPES, pretty_print_account, try_dm

if TYPE_CHECKING:
    from app.config import Config, WebhookFeedType
    from toolbox.misc import GH, Account

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


@final
class GhosttyBot(commands.Bot):
    def __init__(self, config: Config, gh: GH) -> None:
        intents = dc.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=[],
            intents=intents,
            allowed_mentions=dc.AllowedMentions(everyone=False, roles=False),
        )

        self.tree.on_error = interaction_error_handler
        self.config = config
        self.gh = gh
        self.bot_status = BotStatus()

        self._ghostty_emojis: dict[EmojiName, dc.Emoji] = {}
        self.ghostty_emojis = MappingProxyType(self._ghostty_emojis)

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

    @dc.utils.cached_property
    def ghostty_guild(self) -> dc.Guild:
        logger.debug("fetching ghostty guild")
        if self.config.guild_id and (guild := self.get_guild(self.config.guild_id)):
            logger.trace("found ghostty guild")
            return guild
        logger.info(
            "BOT_GUILD_ID unset or specified guild not found; using bot's first guild: "
            "{} (ID: {})",
            self.guilds[0].name,
            self.guilds[0].id,
        )
        return self.guilds[0]

    @dc.utils.cached_property
    def log_channel(self) -> dc.TextChannel:
        logger.debug("fetching log channel")
        channel = self.get_channel(self.config.log_channel_id)
        assert isinstance(channel, dc.TextChannel)
        return channel

    @dc.utils.cached_property
    def help_channel(self) -> dc.ForumChannel:
        logger.debug("fetching help channel")
        channel = self.get_channel(self.config.help_channel_id)
        assert isinstance(channel, dc.ForumChannel)
        return channel

    @dc.utils.cached_property
    def webhook_channels(self) -> dict[WebhookFeedType, dc.TextChannel]:
        channels: dict[WebhookFeedType, dc.TextChannel] = {}
        for feed_type, id_ in self.config.webhook_channel_ids.items():
            logger.debug("fetching {feed_type} webhook channel", feed_type)
            channel = self.ghostty_guild.get_channel(id_)
            if not isinstance(channel, dc.TextChannel):
                msg = (
                    "expected {} webhook channel to be a text channel"
                    if channel
                    else "failed to find {} webhook channel"
                )
                raise TypeError(msg.format(feed_type))
            channels[feed_type] = channel
        return channels

    def is_privileged(self, member: dc.Member) -> bool:
        return not (
            member.get_role(self.config.mod_role_id) is None
            and member.get_role(self.config.helper_role_id) is None
        )

    def is_ghostty_mod(self, user: Account) -> bool:
        member = self.ghostty_guild.get_member(user.id)
        return (
            member is not None and member.get_role(self.config.mod_role_id) is not None
        )

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
        valid_emoji_names = frozenset(get_args(EmojiName))

        for emoji in self.ghostty_guild.emojis:
            if emoji.name in valid_emoji_names:
                self._ghostty_emojis[cast("EmojiName", emoji.name)] = emoji

        if missing_emojis := valid_emoji_names - self._ghostty_emojis.keys():
            await self.log_channel.send(
                "Failed to load the following emojis: " + ", ".join(missing_emojis)
            )
            self._ghostty_emojis |= dict.fromkeys(missing_emojis, "❓")
