import discord

from app import view
from app.setup import bot
from app.utils import SERVER_ONLY, is_dm, is_mod


@bot.tree.context_menu(name="Move message")
@discord.app_commands.default_permissions(manage_messages=True)
@SERVER_ONLY
async def move_message(
    interaction: discord.Interaction, message: discord.Message
) -> None:
    """
    Adds a context menu item to a message to move it to a different channel.
    This is used as a moderation tool to make discussion on-topic.
    """
    assert not is_dm(interaction.user)

    if not is_mod(interaction.user):
        await interaction.response.send_message(
            "You do not have permission to move messages.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "Select a channel to move this message to.",
        view=view.SelectChannel(message, executor=interaction.user),
        ephemeral=True,
    )
