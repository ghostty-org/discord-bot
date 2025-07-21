from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, cast

from .cache import Entity, Issue, PullRequest, entity_cache
from .resolution import resolve_repo_signatures
from app.common.hooks import ProcessedMessage
from app.common.message_moving import get_ghostty_guild
from app.components.github_integration.models import Discussion
from app.setup import bot, config
from app.utils import dynamic_timestamp, escape_special

if TYPE_CHECKING:
    import discord as dc

ENTITY_TEMPLATE = "**{entity.kind} [#{entity.number}](<{entity.html_url}>):** {title}"
EMOJI_NAMES = frozenset({
    "discussion_answered",
    "issue_closed_completed",
    "issue_closed_unplanned",
    "issue_draft",
    "issue_open",
    "pull_closed",
    "pull_draft",
    "pull_merged",
    "pull_open",
})

entity_emojis: dict[str, dc.Emoji] = {}


async def load_emojis() -> None:
    guild = get_ghostty_guild()
    for emoji in guild.emojis:
        if emoji.name in EMOJI_NAMES:
            entity_emojis[emoji.name] = emoji
    if len(entity_emojis) < len(EMOJI_NAMES):
        log_channel = cast("dc.TextChannel", bot.get_channel(config.LOG_CHANNEL_ID))
        await log_channel.send(
            "Failed to load the following emojis: "
            + ", ".join(EMOJI_NAMES - entity_emojis.keys())
        )


def get_entity_emoji(entity: Entity) -> dc.Emoji | None:
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
        emoji_name = "discussion_answered" if entity.answered_by else "issue_draft"
    else:
        msg = f"Unknown entity type: {type(entity)}"
        raise TypeError(msg)

    return entity_emojis.get(emoji_name)


def _format_user_link(login: str) -> str:
    return f"[`{login}`](<https://github.com/{login}>)"


def _format_entity_detail(entity: Entity) -> str:
    if isinstance(entity, Issue):
        if not entity.labels:
            return ""
        if len(entity.labels) > 3:
            labels = entity.labels[:3]
            omission_note = f", and {len(entity.labels) - 3} more"
        else:
            labels, omission_note = entity.labels, ""
        body = f"labels: {', '.join(f'`{label}`' for label in labels)}{omission_note}"
    elif isinstance(entity, PullRequest):
        if not (entity.additions or entity.deletions or entity.changed_files):
            return ""  # Diff size unavailable
        body = (
            f"diff size: `+{entity.additions}` `-{entity.deletions}`"
            f" ({entity.changed_files} files changed)"
        )
    elif isinstance(entity, Discussion):
        if not entity.answered_by:
            return ""
        body = f"answered by {_format_user_link(entity.answered_by.name)}"
    else:
        msg = f"Unknown entity type: {type(entity)}"
        raise TypeError(msg)
    return f"-# {body}\n"


def _format_mention(entity: Entity) -> str:
    headline = ENTITY_TEMPLATE.format(entity=entity, title=escape_special(entity.title))

    # https://github.com/owner/repo/issues/12
    # -> https://github.com  owner  repo  issues  12
    #    0                   1      2     3       4
    domain, owner, name, *_ = entity.html_url.rsplit("/", 4)
    fmt_ts = partial(dynamic_timestamp, entity.created_at)
    subtext = (
        f"-# by {_format_user_link(entity.user.name)}"
        f" in [`{owner}/{name}`](<{domain}/{owner}/{name}>)"
        f" on {fmt_ts('D')} ({fmt_ts('R')})\n"
    )
    entity_detail = _format_entity_detail(entity)

    emoji = get_entity_emoji(entity) or "❓"
    return f"{emoji} {headline}\n{subtext}{entity_detail}"


async def entity_message(message: dc.Message) -> ProcessedMessage:
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

    return ProcessedMessage(
        content="\n".join(dict.fromkeys(entities)), item_count=len(entities)
    )
