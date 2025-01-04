from typing import cast

import discord

from app.setup import bot, config
from app.utils import (
    SERVER_ONLY,
    GuildTextChannels,
    get_or_create_webhook,
    is_dm,
    is_helper,
    is_mod,
    move_message_via_webhook,
)


class SelectChannel(discord.ui.View):
    def __init__(self, message: discord.Message, executor: discord.Member) -> None:
        super().__init__()
        self.message = message
        self.executor = executor
        self._used = False

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread],
        placeholder="Select a channel",
        min_values=1,
        max_values=1,
    )
    async def select_channel(
        self, interaction: discord.Interaction, sel: discord.ui.ChannelSelect
    ) -> None:
        if self._used:
            await interaction.response.send_message(
                "Channel selector was already used.", ephemeral=True
            )
            return
        self._used = True
        channel = await bot.fetch_channel(sel.values[0].id)
        assert isinstance(channel, (discord.abc.GuildChannel, discord.Thread))
        if channel.id == self.message.channel.id:
            await interaction.response.send_message(
                "You can't move a message to the same channel.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        webhook_channel, thread = (
            (channel.parent, channel)
            if isinstance(channel, discord.Thread)
            else (channel, discord.utils.MISSING)
        )
        assert isinstance(webhook_channel, GuildTextChannels)

        webhook = await get_or_create_webhook("Ghostty Moderator", webhook_channel)
        await move_message_via_webhook(
            webhook, self.message, self.executor, thread=thread
        )
        await interaction.followup.send(
            content=f"Moved the message to {channel.mention}.",
            view=Ghostping(
                cast(discord.Member, self.message.author),
                cast(discord.abc.Messageable, channel),
            ),
        )


class Ghostping(discord.ui.View):
    def __init__(
        self, author: discord.Member, channel: discord.abc.Messageable
    ) -> None:
        super().__init__()
        self._author = author
        self._channel = channel

    @discord.ui.button(
        label="Ghostping",
        emoji="👻",
        style=discord.ButtonStyle.secondary,
    )
    async def ghostping(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await (await self._channel.send(self._author.mention)).delete()
        escaped_name = self._author.name.replace("_", "\\_")
        await interaction.followup.send(f"Ghostpinged {escaped_name}.", ephemeral=True)


class HelpPostTitle(discord.ui.Modal, title="Turn into #help post"):
    title_ = discord.ui.TextInput(
        label="#help post title", style=discord.TextStyle.short
    )

    def __init__(self, message: discord.Message) -> None:
        super().__init__()
        self._message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        help_channel = cast(
            discord.ForumChannel, bot.get_channel(config.HELP_CHANNEL_ID)
        )
        await interaction.response.defer(ephemeral=True)

        webhook = await get_or_create_webhook("Ghostty Moderator", help_channel)
        msg = await move_message_via_webhook(
            webhook,
            self._message,
            cast(discord.Member, interaction.user),
            thread_name=self.title_.value,
        )
        await (await msg.channel.send(self._message.author.mention)).delete()

        # Apparently msg.channel.mention is unavailable
        await interaction.followup.send(
            content=f"Help post created: <#{msg.channel.id}>", ephemeral=True
        )


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

    if not (is_mod(interaction.user) or is_helper(interaction.user)):
        await interaction.response.send_message(
            "You do not have permission to move messages.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "Select a channel to move this message to.",
        view=SelectChannel(message, executor=interaction.user),
        ephemeral=True,
    )


@bot.tree.context_menu(name="Turn into #help post")
@discord.app_commands.default_permissions(manage_messages=True)
@SERVER_ONLY
async def turn_into_help_post(
    interaction: discord.Interaction, message: discord.Message
) -> None:
    """
    An extension of the move_message function that creates a #help post and then
    moves the message to that channel.
    """
    assert not is_dm(interaction.user)

    if not (is_mod(interaction.user) or is_helper(interaction.user)):
        await interaction.response.send_message(
            "You do not have permission to use this action.", ephemeral=True
        )
        return

    await interaction.response.send_modal(HelpPostTitle(message))
