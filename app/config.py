# pyright: reportUnannotatedClassAttribute=false

from contextvars import ContextVar
from functools import cached_property
from typing import TYPE_CHECKING, Any, Literal

import discord as dc
from githubkit import GitHub, TokenAuthStrategy
from loguru import logger
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from toolbox.discord import Account

type WebhookFeedType = Literal["main", "discussions"]

# This maps valid special ghostty-org repo prefixes to appropriate repo names. Since the
# actual repo names are also valid prefixes, they can be viewed as self-mapping aliases.
REPO_ALIASES = {
    "ghostty": "ghostty",
    "main": "ghostty",
    "web": "website",
    "website": "website",
    "discord-bot": "discord-bot",
    "bot": "discord-bot",
    "bobr": "discord-bot",
}


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BOT_", enable_decoding=False)

    def __init__(
        self, env_file: str, *args: Any, bot: dc.Client, **kwargs: Any
    ) -> None:
        logger.info("loading config from {}", env_file)
        self.model_config["env_file"] = env_file
        super().__init__(*args, **kwargs)

        self._bot = bot

    token: SecretStr

    github_org: str
    github_token: SecretStr
    github_webhook_url: SecretStr
    github_webhook_secret: SecretStr | None = None

    accept_invite_url: str
    sentry_dsn: SecretStr | None = None

    help_channel_tag_ids: dict[str, int]

    guild_id: int | None = None
    help_channel_id: int
    log_channel_id: int
    media_channel_id: int
    showcase_channel_id: int
    serious_channel_ids: list[int]
    webhook_channel_ids: dict[WebhookFeedType, int]

    mod_role_id: int
    helper_role_id: int

    @field_validator("serious_channel_ids", mode="before")
    @classmethod
    def parse_id_list(cls, value: str) -> list[int]:
        return list(map(int, value.split(",")))

    @field_validator("help_channel_tag_ids", "webhook_channel_ids", mode="before")
    @classmethod
    def parse_id_mapping(cls, value: str) -> dict[str, int]:
        return {
            name: int(id_)
            for name, id_ in (pair.split(":") for pair in value.split(","))
        }

    @cached_property
    def ghostty_guild(self) -> dc.Guild:
        logger.debug("fetching ghostty guild")
        if (id_ := self.guild_id) and (guild := self._bot.get_guild(id_)):
            logger.trace("found ghostty guild")
            return guild
        guild = self._bot.guilds[0]
        logger.info(
            "BOT_GUILD_ID unset or specified guild not found; using bot's first guild: "
            "{} (ID: {})",
            guild.name,
            guild.id,
        )
        return guild

    @cached_property
    def log_channel(self) -> dc.TextChannel:
        logger.debug("fetching log channel")
        channel = self._bot.get_channel(self.log_channel_id)
        assert isinstance(channel, dc.TextChannel)
        return channel

    @cached_property
    def help_channel(self) -> dc.ForumChannel:
        logger.debug("fetching help channel")
        channel = self._bot.get_channel(self.help_channel_id)
        assert isinstance(channel, dc.ForumChannel)
        return channel

    @cached_property
    def webhook_channels(self) -> dict[WebhookFeedType, dc.TextChannel]:
        channels: dict[WebhookFeedType, dc.TextChannel] = {}
        for feed_type, id_ in self.webhook_channel_ids.items():
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
            member.get_role(self.mod_role_id) is None
            and member.get_role(self.helper_role_id) is None
        )

    def is_ghostty_mod(self, user: Account) -> bool:
        member = self.ghostty_guild.get_member(user.id)
        return member is not None and member.get_role(self.mod_role_id) is not None


config_var = ContextVar[Config]("config")
config = config_var.get
gh_var = ContextVar[GitHub[TokenAuthStrategy]]("gh")
gh = gh_var.get
