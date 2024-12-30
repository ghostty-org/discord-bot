import discord

from app.setup import bot, config


@bot.event
async def on_thread_update(before: discord.Thread, after: discord.Thread) -> None:
    if before.parent_id != config.HELP_CHANNEL_ID:
        return
    if not (new_tags := set(after.applied_tags) - set(before.applied_tags)):
        return
    if not any("solved" in tag.name.casefold() for tag in new_tags):
        return
    await after.edit(name=f"[SOLVED] {after.name}", archived=True)
