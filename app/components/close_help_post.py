from typing import cast

import discord

from app.setup import bot, config
from app.utils import SERVER_ONLY, is_dm, is_helper, is_mod


@bot.tree.command(name="close", description="Mark current post as resolved.")
@SERVER_ONLY
async def close_post(
    interaction: discord.Interaction, moved_to_github: bool = False
) -> None:
    if not (
        isinstance(post := interaction.channel, discord.Thread)
        and post.parent_id == config.HELP_CHANNEL_ID
    ):
        await interaction.response.send_message(
            f"This command can only be used in <#{config.HELP_CHANNEL_ID}> posts.",
            ephemeral=True,
        )
        return

    assert not is_dm(interaction.user)
    if not (
        is_mod(interaction.user)
        or is_helper(interaction.user)
        or interaction.user.id == post.owner_id
    ):
        await interaction.response.send_message(
            "You don't have permission to close this post.", ephemeral=True
        )
        return

    if post.archived:
        await interaction.response.send_message(
            "This post is already closed.", ephemeral=True
        )
        return

    help_tags = cast(discord.ForumChannel, post.parent).available_tags
    desired_tag_id = config.HELP_CHANNEL_TAG_IDS[
        "github" if moved_to_github else "solved"
    ]
    tag = next(tag for tag in help_tags if tag.id == desired_tag_id)
    await post.add_tags(tag)

    await interaction.response.defer(ephemeral=True)

    if not moved_to_github and "[solved]" not in post.name.casefold():
        await post.edit(name=f"[SOLVED] {post.name}")
    await post.edit(archived=True)

    await interaction.followup.send("Post marked as resolved.", ephemeral=True)
