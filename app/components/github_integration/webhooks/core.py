from __future__ import annotations

from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

import discord as dc

from app.components.github_integration.models import GitHubUser
from app.utils import truncate

if TYPE_CHECKING:
    from githubkit.versions.latest.models import SimpleUser

    from app.bot import EmojiName, GhosttyBot
    from app.config import WebhookFeedType

type EmbedColor = Literal["green", "red", "purple", "gray", "orange", "blue"]

EMBED_COLORS: dict[EmbedColor, int] = {
    "green": 0x3FB950,
    "purple": 0xAB7DF8,
    "red": 0xF85149,
    "gray": 0x9198A1,
    "orange": 0xEDB74A,
    "blue": 0x4C8CED,
}


class EmbedContentArgs(TypedDict, total=False):
    title: str
    url: str
    description: str | None


class EmbedContent(NamedTuple):
    title: str
    url: str
    body: str | None = None

    @property
    def dict(self) -> EmbedContentArgs:
        args: EmbedContentArgs = {"title": self.title, "url": self.url}
        if self.body:
            args["description"] = truncate(self.body, 500)
        return args


class Footer(NamedTuple):
    icon: EmojiName
    text: str

    def dict(self, bot: GhosttyBot) -> dict[str, str | None]:
        return {
            "text": self.text,
            "icon_url": getattr(bot.ghostty_emojis[self.icon], "url", None),
        }


async def send_embed(  # noqa: PLR0913
    bot: GhosttyBot,
    actor: SimpleUser,
    content: EmbedContent,
    footer: Footer,
    *,
    color: EmbedColor | None = None,
    feed_type: WebhookFeedType = "main",
) -> None:
    author = GitHubUser(**actor.model_dump())
    embed = (
        dc.Embed(color=color and EMBED_COLORS.get(color), **content.dict)
        .set_footer(**footer.dict(bot))
        .set_author(**author.model_dump())
    )
    await bot.webhook_channels[feed_type].send(embed=embed)
