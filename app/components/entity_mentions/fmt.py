import re
from typing import cast

import discord
from githubkit.versions.latest.models import Issue, PullRequest

from app.setup import bot, config

from .cache import Entity, EntityKind, RepoName, entity_cache

GITHUB_URL = "https://github.com"
ENTITY_REGEX = re.compile(r"(?:\b(web|bot|main))?#(\d{1,6})(?!\.\d)\b")
ENTITY_TEMPLATE = "**{kind} [#{entity.number}](<{entity.html_url}>):** {entity.title}"
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
    headline = ENTITY_TEMPLATE.format(kind=kind, entity=entity)

    # Include author and creation date
    author = entity.user.login
    subtext = (
        f"-# by [`{author}`](<{GITHUB_URL}/{author}>)"
        f" on {entity.created_at:%b %d, %Y}\n"
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

    return f"{emoji or ":question:"} {headline}\n{subtext}"


def entity_message(message: discord.Message) -> tuple[str, int]:
    matches = dict.fromkeys(m.groups() for m in ENTITY_REGEX.finditer(message.content))
    omitted = 0
    if len(matches) > 10:
        # Too many mentions, preventing a DoS
        omitted = len(matches) - 10
        matches = list(matches)[:10]

    entities: list[str] = []
    for repo_name, number_ in matches:
        number = int(number_)
        try:
            kind, entity = entity_cache[cast(RepoName, repo_name or "main"), number]
        except KeyError:
            continue
        if entity.number < 10 and repo_name is None:
            # Ignore single-digit mentions (likely a false positive)
            continue
        entities.append(_format_mention(entity, kind))

    if len("\n".join(entities)) > 2000:
        while len("\n".join(entities)) > 1975:  # Accounting for omission note
            entities.pop()
            omitted += 1
        entities.append(f"-# Omitted {omitted} mention" + ("s" * (omitted > 1)))

    return "\n".join(dict.fromkeys(entities)), len(entities)
