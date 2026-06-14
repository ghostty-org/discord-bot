# pyright: reportUnannotatedClassAttribute=false

from contextvars import ContextVar
from functools import cached_property
from typing import TYPE_CHECKING, Annotated, Any, Literal, NamedTuple, override

import discord as dc
from githubkit import GitHub, TokenAuthStrategy
from loguru import logger
from pydantic import (
    AliasChoices,
    BaseModel,
    DirectoryPath,
    Field,
    SecretStr,
    TypeAdapter,
)
from pydantic_settings import (
    BaseSettings,
    CliSuppress,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

if TYPE_CHECKING:
    from pydantic_settings import PydanticBaseSettingsSource

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
ENV_PREFIX = "BOT__"


def validate_type[T](obj: object, typ: type[T]) -> T:
    adapter = TypeAdapter(typ, config={"arbitrary_types_allowed": True})
    return adapter.validate_python(obj, strict=True)


def _alias(name: str) -> AliasChoices:
    return AliasChoices(name, ENV_PREFIX + name.upper())


class ConfigRoles(BaseModel):
    mod: Annotated[int, Field(description="the id of the mod role")]
    helper: Annotated[int, Field(description="the id of the helper role")]


class ConfigTokens(BaseModel):
    discord: Annotated[SecretStr, Field(description="the Discord bot token")]
    github: Annotated[SecretStr, Field(description="the GitHub token")]


class ConfigChannels(BaseModel):
    hcb_feed: Annotated[int, Field(description="the id of the hcb feed channel")]
    help: Annotated[int, Field(description="the id of the help forum channel")]
    log: Annotated[int, Field(description="the id of the log channel")]
    media: Annotated[int, Field(description="the id of the media channel")]
    showcase: Annotated[int, Field(description="the id of the showcase channel")]
    help_tags: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "a table of tag_name → tag_id pairs; the tag names are `moved`, `solved`,"
            " `stale`, and `duplicate`"
        ),
    )


class Channels(NamedTuple):
    hcb_feed: dc.TextChannel
    help: dc.ForumChannel
    log: dc.TextChannel


class WebhookChannels(BaseModel):
    main: Annotated[int, Field(description="the id of the main webhook feed channel")]
    discussions: Annotated[
        int, Field(description="the id of the discussions webhook feed channel")
    ]


class ConfigWebhook(BaseModel):
    _bot: dc.Client
    url: Annotated[SecretStr, Field(description="the URL to receive events from")]
    secret: Annotated[
        SecretStr | None, Field(description="a token for validating events")
    ] = None
    channel_ids: Annotated[
        WebhookChannels,
        Field(
            alias="channels",
            description=(
                "a table of feed_type → channel_id pairs; the feed type names are"
                " `main` and `discussions`"
            ),
        ),
    ]

    @cached_property
    def channels(self) -> dict[WebhookFeedType, dc.TextChannel]:
        assert self._bot
        channels = {
            "main": self._bot.get_channel(self.channel_ids.main),
            "discussions": self._bot.get_channel(self.channel_ids.discussions),
        }
        return validate_type(channels, dict[WebhookFeedType, dc.TextChannel])


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        cli_prog_name="uv run -m app",
        cli_avoid_json=True,
        cli_hide_none_type=True,
        cli_parse_args=True,
        cli_kebab_case=True,
        cli_use_class_docs_for_groups=True,
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        toml_file="config.toml",
    )

    bot: CliSuppress[dc.Client]
    accept_invite_url: Annotated[
        str, Field(description="a URL to visit to accept the Ghostty invite")
    ]
    guild_id: Annotated[
        int | None,
        Field(
            description=(
                "the id of the server you prepared (useful when your bot is in multiple"
                " servers)"
            )
        ),
    ] = None
    data_dir: Annotated[
        DirectoryPath, Field(description="a directory path for persistent state")
    ]
    sentry_dsn: Annotated[SecretStr | None, Field(description="the Sentry DSN")] = None

    tokens: ConfigTokens
    role_ids: Annotated[ConfigRoles, Field(validation_alias=_alias("roles"))]
    channel_ids: Annotated[ConfigChannels, Field(validation_alias=_alias("channels"))]
    webhook: ConfigWebhook

    @override
    def model_post_init(self, context: Any, /) -> None:
        self.webhook._bot = self.bot  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            env_settings,
            init_settings,
            TomlConfigSettingsSource(settings_cls),
            dotenv_settings,
        )

    @cached_property
    def channels(self) -> Channels:
        logger.debug("fetching channels: hcb-feed, help, log")
        channels = (
            self.bot.get_channel(self.channel_ids.hcb_feed),
            self.bot.get_channel(self.channel_ids.help),
            self.bot.get_channel(self.channel_ids.log),
        )
        return validate_type(channels, Channels)

    @cached_property
    def ghostty_guild(self) -> dc.Guild:
        logger.debug("fetching ghostty guild")
        if (id_ := self.guild_id) and (guild := self.bot.get_guild(id_)):
            logger.trace("found ghostty guild")
            return guild
        guild = self.bot.guilds[0]
        logger.info(
            "BOT_GUILD_ID unset or specified guild not found; using bot's first guild: "
            "{name} (ID: {id})",
            name=guild.name,
            id=guild.id,
        )
        return guild

    def is_privileged(self, member: dc.Member) -> bool:
        return not (
            member.get_role(self.role_ids.mod) is None
            and member.get_role(self.role_ids.helper) is None
        )

    def is_ghostty_mod(self, user: Account) -> bool:
        member = self.ghostty_guild.get_member(user.id)
        return member is not None and member.get_role(self.role_ids.mod) is not None


config_var = ContextVar[Config]("config")
config = config_var.get
gh_var = ContextVar[GitHub[TokenAuthStrategy]]("gh")
gh = gh_var.get
