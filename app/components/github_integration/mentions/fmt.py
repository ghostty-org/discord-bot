from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, cast

from .cache import Entity, Issue, PullRequest, entity_cache
from .resolution import resolve_repo_signatures
from app.components.github_integration.models import Discussion
from app.setup import bot, config
from app.utils import dynamic_timestamp, escape_special, get_ghostty_guild

if TYPE_CHECKING:
    import discord

ENTITY_TEMPLATE = "**{entity.kind} [#{entity.number}](<{entity.html_url}>):** {title}"
EMOJI_NAMES = frozenset(
    {
        "discussion_answered",
        "issue_closed_completed",
        "issue_closed_unplanned",
        "issue_draft",
        "issue_open",
        "pull_closed",
        "pull_draft",
        "pull_merged",
        "pull_open",
    }
)

entity_emojis: dict[str, discord.Emoji] = {}


async def load_emojis() -> None:
    guild = get_ghostty_guild()
    for emoji in guild.emojis:
        if emoji.name in EMOJI_NAMES:
            entity_emojis[emoji.name] = emoji
    if len(entity_emojis) < len(EMOJI_NAMES):
        log_channel = cast(
            "discord.TextChannel", bot.get_channel(config.LOG_CHANNEL_ID)
        )
        await log_channel.send(
            "Failed to load the following emojis: "
            + ", ".join(EMOJI_NAMES - entity_emojis.keys())
        )


def get_entity_emoji(entity: Entity) -> discord.Emoji | None:
    if isinstance(entity, Issue):
        state = "closed_" if entity.closed else "open"
        if entity.closed:
            state += "completed" if entity.state_reason == "completed" else "unplanned"
        emoji_name = f"issue_{state}"
    elif isinstance(entity, PullRequest):
        emoji_name = "pull_" + (
            "draft" if entity.draft
            else "merged" if entity.merged
            else "closed" if entity.closed
            else "open"
        )  # fmt: skip
    elif isinstance(entity, Discussion):
        emoji_name = "discussion_answered" if entity.answered else "issue_draft"
    else:
        msg = f"Unknown entity type: {type(entity)}"
        raise TypeError(msg)

    return entity_emojis.get(emoji_name)


def _format_mention(entity: Entity) -> str:
    headline = ENTITY_TEMPLATE.format(entity=entity, title=escape_special(entity.title))

    # https://github.com/owner/repo/issues/12
    # -> https://github.com  owner  repo  issues  12
    #    0                   1      2     3       4
    domain, owner, name, *_ = entity.html_url.rsplit("/", 4)
    author = entity.user.name
    fmt_ts = partial(dynamic_timestamp, entity.created_at)
    subtext = (
        f"-# by [`{author}`](<{domain}/{author}>)"
        f" in [`{owner}/{name}`](<{domain}/{owner}/{name}>)"
        f" on {fmt_ts('D')} ({fmt_ts('R')})\n"
    )

    emoji = get_entity_emoji(entity) or "❓"
    return f"{emoji} {headline}\n{subtext}"


async def entity_message(message: discord.Message) -> tuple[str, int]:
    matches = list(dict.fromkeys([r async for r in resolve_repo_signatures(message)]))

    entities = [
        _format_mention(entity)
        for entity in await asyncio.gather(
            *(entity_cache.get(m) for m in matches), return_exceptions=True
        )
        if not isinstance(entity, BaseException)
    ]

    if len("\n".join(entities)) > 2000:
        while len("\n".join(entities)) > 1970:  # Accounting for omission note
            entities.pop()
        entities.append("-# Some mentions were omitted")

    return "\n".join(dict.fromkeys(entities)), len(entities)
