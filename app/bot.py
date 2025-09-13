from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast, final, get_args, override

import discord as dc
from discord.ext import commands
from loguru import logger

from app.errors import handle_error, interaction_error_handler
from app.status import BotStatus
from app.utils import is_mod, try_dm

if TYPE_CHECKING:
    from githubkit import GitHub, TokenAuthStrategy

    from app.config import Config, WebhookFeedType
    from app.utils import Account

EmojiName = Literal[
    "commit",
    "discussion",
    "discussion_answered",
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
    def __init__(self, config: Config, gh: GitHub[TokenAuthStrategy]) -> None:
        intents = dc.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            allowed_mentions=dc.AllowedMentions(everyone=False, roles=False),
        )

        self.tree.on_error = interaction_error_handler
        self.config = config
        self.gh = gh
        self.bot_status = BotStatus()
        self.background_tasks = set[asyncio.Task[None]]()

        self._ghostty_emojis: dict[EmojiName, dc.Emoji] = {}
        self.ghostty_emojis = MappingProxyType(self._ghostty_emojis)

    @override
    async def on_error(self, event_method: str, /, *args: Any, **kwargs: Any) -> None:
        handle_error(cast("BaseException", sys.exception()))

    @override
    async def load_extension(self, name: str, *, package: str | None = None) -> None:
        logger.debug("loading extension {}", name.removeprefix("app.components."))
        await super().load_extension(name, package=package)

    @override
    async def setup_hook(self) -> None:
        coros = (
            self.load_extension(f"app.components.{file.stem}")
            for file in (Path(__file__).parent / "components").iterdir()
            if not file.name.startswith("_")
        )
        await asyncio.gather(*coros)
        logger.info("loaded {} extensions", len(self.extensions))

    async def on_ready(self) -> None:
        self.bot_status.last_login_time = dt.datetime.now(tz=dt.UTC)
        await self._load_emojis()
        logger.info("logged in as {}", self.user)

    async def _load_emojis(self) -> None:
        valid_emoji_names = frozenset(get_args(EmojiName))

        for emoji in self.ghostty_guild.emojis:
            if emoji.name in valid_emoji_names:
                self._ghostty_emojis[cast("EmojiName", emoji.name)] = emoji

        if missing_emojis := valid_emoji_names - self._ghostty_emojis.keys():
            await self.log_channel.send(
                "Failed to load the following emojis: " + ", ".join(missing_emojis)
            )
            self._ghostty_emojis |= dict.fromkeys(missing_emojis, "❓")

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

    def is_ghostty_mod(self, user: Account) -> bool:
        member = self.ghostty_guild.get_member(user.id)
        return member is not None and is_mod(member)

    @override
    async def on_message(self, message: dc.Message, /) -> None:
        # Ignore our own messages
        if message.author == self.user:
            return

        # Simple test
        if message.guild is None and message.content == "ping":
            logger.debug("ping sent by @{}", message.author.name)
            await try_dm(message.author, "pong")
            return

        await self.process_commands(message)
