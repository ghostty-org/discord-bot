from __future__ import annotations

import asyncio
from typing import cast

import discord
from githubkit.versions.latest.models import Issue, PullRequest

from app.components.entity_mentions.resolution import resolve_repo_signatures
from app.setup import bot, config
from app.utils import escape_special

from .cache import Entity, EntityKind, entity_cache

ENTITY_TEMPLATE = "**{kind} [#{entity.number}](<{entity.html_url}>):** {title}"
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
    guild = next(g for g in bot.guilds if "ghostty" in g.name.casefold())
    for emoji in guild.emojis:
        if emoji.name in EMOJI_NAMES:
            entity_emojis[emoji.name] = emoji
    if len(entity_emojis) < len(EMOJI_NAMES):
        log_channel = cast(discord.TextChannel, bot.get_channel(config.LOG_CHANNEL_ID))
        await log_channel.send(
            "Failed to load the following emojis: "
            + ", ".join(EMOJI_NAMES - entity_emojis.keys())
        )


def _format_mention(entity: Entity, kind: EntityKind) -> str:
    title = escape_special(entity.title)
    headline = ENTITY_TEMPLATE.format(kind=kind, entity=entity, title=title)

    # https://github.com/owner/repo/issues/12
    # -> https://github.com  owner  repo  issues  12
    #    0                   1      2     3       4
    domain, owner, name, *_ = entity.html_url.rsplit("/", 4)
    author = entity.user.login
    timestamp = int(entity.created_at.timestamp())
    subtext = (
        f"-# by [`{author}`](<{domain}/{author}>)"
        f" in [`{owner}/{name}`](<{domain}/{owner}/{name}>)"
        f" on <t:{timestamp}:D> (<t:{timestamp}:R>)\n"
    )

    if isinstance(entity, Issue):
        state = "open" if entity.state == "open" else "closed_"
        if entity.state == "closed":
            state += "completed" if entity.state_reason == "completed" else "unplanned"
        emoji = entity_emojis.get(f"issue_{state}")
    elif isinstance(entity, PullRequest):
        state = "draft" if entity.draft else "merged" if entity.merged else entity.state
        emoji = entity_emojis.get(f"pull_{state}")
    else:
        # Discussion
        answered = getattr(entity, "answered", False)
        emoji = entity_emojis.get("discussion_answered" if answered else "issue_draft")

    return f"{emoji or ':question:'} {headline}\n{subtext}"


async def entity_message(message: discord.Message) -> tuple[str, int]:
    matches = list(
        dict.fromkeys([r async for r in resolve_repo_signatures(message.content)])
    )

    entities = [
        _format_mention(outcome[1], outcome[0])
        for outcome in await asyncio.gather(
            *(entity_cache.get(m) for m in matches), return_exceptions=True
        )
        if not isinstance(outcome, BaseException)
    ]

    if len("\n".join(entities)) > 2000:
        while len("\n".join(entities)) > 1970:  # Accounting for omission note
            entities.pop()
        entities.append("-# Some mentions were omitted")

    return "\n".join(dict.fromkeys(entities)), len(entities)
