import asyncio
from functools import partial
from typing import TYPE_CHECKING

from .cache import entity_cache
from .resolution import resolve_entity_signatures
from app.bot import emojis
from app.components.github_integration.models import (
    Discussion,
    Issue,
    PRStack,
    PullRequest,
    StackedPR,
)
from toolbox.discord import dynamic_timestamp, escape_special
from toolbox.github import format_diff_note
from toolbox.linker import ProcessedMessage

if TYPE_CHECKING:
    import discord as dc

    from app.components.github_integration.models import Entity


def get_entity_emoji(entity: Entity | StackedPR) -> dc.Emoji | str:
    if isinstance(entity, Issue):
        state = "open"
        if entity.closed:
            state = "closed_"
            state += "completed" if entity.state_reason == "completed" else "unplanned"
        emoji_name = "issue_" + state
    elif isinstance(entity, (PullRequest, StackedPR)):
        emoji_name = "pull_" + (
            "merged" if entity.merged
            else "closed" if entity.closed
            else "draft" if entity.draft
            else "open"
        )  # fmt: skip
    elif isinstance(entity, Discussion):
        emoji_name = "discussion"
        if entity.closed or entity.answered_by:
            emoji_name += (
                "_duplicate" if entity.state_reason == "DUPLICATE"
                else "_outdated" if entity.state_reason == "OUTDATED"
                else "_answered"
            )  # fmt: skip
    else:
        msg = f"Unknown entity type: {type(entity)}"
        raise TypeError(msg)

    return emojis()[emoji_name]


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
        body = format_diff_note(
            entity.additions, entity.deletions, entity.changed_files
        )
        if body is None:
            return ""  # Diff size unavailable
    elif isinstance(entity, Discussion):
        if not entity.answered_by:
            return ""
        body = f"answered by {entity.answered_by.format()}"
    else:
        msg = f"Unknown entity type: {type(entity)}"
        raise TypeError(msg)
    return f"-# {body}\n"


def _collapse(entries: list[str], *, limit: int, placeholder: str) -> list[str]:
    if len(entries) <= limit:
        return entries
    start = entries[: limit // 2]
    end = entries[-(limit // 2) :]
    return [*start, placeholder, *end]


def _format_pr_stack(stack: PRStack) -> str:
    heading = f"{emojis()['stack']} **Stack #{stack.number}**"

    prs = stack.pull_requests
    pr_list = _collapse(
        [
            f"* {get_entity_emoji(pr)} **[#{pr.number}](<{pr.html_url}>):** {
                escape_special(pr.title)
            }"
            for pr in reversed(prs)
        ],
        limit=9,
        placeholder=f"* … *({len(prs) - 8} more)*",
    )

    owner, name = stack.owner, stack.repo_name
    base = f"[`{owner}/{name}:{prs[0].base_ref}`](<https://github.com/{owner}/{name}>)"
    path_parts = _collapse(
        [base, *(f"`{pr.head_ref}`" for pr in prs)], limit=5, placeholder="…"
    )
    path = f"-# {' ← '.join(path_parts)}"

    return "\n".join((heading, *pr_list, path, ""))


def _format_mention(entity: Entity) -> str:
    if isinstance(entity, PRStack):
        return _format_pr_stack(entity)
    headline = f"**{entity.kind} [#{entity.number}](<{entity.html_url}>):** {
        escape_special(entity.title)
    }"

    owner, name = entity.owner, entity.repo_name
    fmt_ts = partial(dynamic_timestamp, entity.created_at)
    subtext = (
        f"-# by {entity.user.format()}"
        f" in [`{owner}/{name}`](<https://github.com/{owner}/{name}>)"
        f" on {fmt_ts('D')} ({fmt_ts('R')})\n"
    )
    entity_detail = _format_entity_detail(entity)

    emoji = get_entity_emoji(entity)
    return f"{emoji} {headline}\n{subtext}{entity_detail}"


async def extract_entities(message: dc.Message) -> list[Entity]:
    matches = list(dict.fromkeys([r async for r in resolve_entity_signatures(message)]))
    cache_hits = await asyncio.gather(
        *map(entity_cache.get, matches), return_exceptions=True
    )
    return [
        entity
        for entity in cache_hits
        if entity and not isinstance(entity, BaseException)
    ]


async def entity_message(message: dc.Message) -> ProcessedMessage:
    entities = list(map(_format_mention, await extract_entities(message)))

    if len("\n".join(entities)) > 2000:
        while len("\n".join(entities)) > 1970:  # Accounting for omission note
            entities.pop()
        entities.append("-# Some mentions were omitted")

    return ProcessedMessage(
        content="\n".join(dict.fromkeys(entities)), item_count=len(entities)
    )
