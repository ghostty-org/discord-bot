# pyright: reportUnannotatedClassAttribute=false

import sys
from typing import Literal

from githubkit import GitHub
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    model_config = SettingsConfigDict(
        env_prefix="BOT_", env_file=".env", enable_decoding=False
    )

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


if "pytest" in sys.modules:
    Config.model_config["env_file"] = ".env.example"


# https://github.com/pydantic/pydantic-settings/issues/201
config = Config()  # pyright: ignore[reportCallIssue]
gh = GitHub(config.github_token.get_secret_value())
