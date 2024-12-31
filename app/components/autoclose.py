from collections.abc import Iterable

import discord

from app.setup import bot, config


@bot.event
async def on_thread_update(before: discord.Thread, after: discord.Thread) -> None:
    if before.parent_id != config.HELP_CHANNEL_ID:
        return
    if (old_tags := set(before.applied_tags)) == (new_tags := set(after.applied_tags)):
        return
    if _has_solved_tag(new_tags - old_tags):
        # A "Solved" tag was added
        await after.edit(name=f"[SOLVED] {after.name}", archived=True)
    elif _has_solved_tag(old_tags - new_tags):
        # A "Solved" tag was removed
        await after.edit(name=after.name.removeprefix("[SOLVED] "), archived=False)


def _has_solved_tag(tags: Iterable[discord.ForumTag]) -> bool:
    return any("solved" in tag.name.casefold() for tag in tags)
