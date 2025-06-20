import datetime as dt
from typing import Self, cast

import discord

from app.setup import bot, config
from app.utils import (
    GuildTextChannel,
    MovedMessage,
    MovedMessageLookupFailed,
    get_or_create_webhook,
    is_dm,
    is_helper,
    is_mod,
    message_can_be_moved,
    move_message_via_webhook,
    truncate,
)

# From https://discord.com/developers/docs/topics/opcodes-and-status-codes#json-json-error-codes.
MAXIMUM_NUMBER_OF_ACTIVE_THREADS_REACHED = 160006

MOVED_MESSAGE_MODIFICATION_CUTOFF = dt.datetime(
    year=2025, month=6, day=18, hour=23, minute=10, tzinfo=dt.UTC
)

NO_THREAD_PERMS = (
    "⚠️ I don't have the required permissions to create private "  # test: allow-vs16
    "threads; please contact a moderator! In the meantime, use the modal "
    "instead."
)
TOO_MANY_THREADS = (
    "⚠️ There are too many active threads in this server! Use the "  # test: allow-vs16
    "modal instead, or try again later."
)
EDIT_IN_THREAD_HINT = (
    "Please send a message containing the message's new content.\n"
    "-# **Hint:** you can copy your message's content by pressing "
    '"Copy Text" in the context menu. Any attachments you upload are '
    "also added to your message."
)


class SelectChannel(discord.ui.View):
    def __init__(self, message: discord.Message, executor: discord.Member) -> None:
        super().__init__()
        self.message = message
        self.executor = executor

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread],
        placeholder="Select a channel",
        min_values=1,
        max_values=1,
    )
    async def select_channel(
        self,
        interaction: discord.Interaction,
        sel: discord.ui.ChannelSelect[Self],
    ) -> None:
        channel = await bot.fetch_channel(sel.values[0].id)
        assert isinstance(channel, GuildTextChannel)
        if channel.id == self.message.channel.id:
            await interaction.response.edit_message(
                content=(
                    "You can't move a message to the same channel."
                    " Pick a different channel."
                )
            )
            return

        await interaction.response.defer()
        webhook_channel, thread = (
            (channel.parent, channel)
            if isinstance(channel, discord.Thread)
            else (channel, discord.utils.MISSING)
        )
        assert isinstance(webhook_channel, discord.TextChannel | discord.ForumChannel)

        webhook = await get_or_create_webhook(webhook_channel)
        await move_message_via_webhook(
            webhook, self.message, self.executor, thread=thread
        )
        await interaction.edit_original_response(
            content=f"Moved the message to {channel.mention}.",
            view=Ghostping(cast("discord.Member", self.message.author), channel),
        )


class Ghostping(discord.ui.View):
    def __init__(self, author: discord.Member, channel: GuildTextChannel) -> None:
        super().__init__()
        self._author = author
        self._channel = channel

    @discord.ui.button(
        label="Ghostping",
        emoji="👻",
        style=discord.ButtonStyle.gray,
    )
    async def ghostping(
        self, interaction: discord.Interaction, button: discord.ui.Button[Self]
    ) -> None:
        button.disabled = True
        await interaction.response.edit_message(
            content=(
                f"Moved the message to {self._channel.mention}"
                f" and ghostpinged {self._author.mention}."
            ),
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await (await self._channel.send(self._author.mention)).delete()


class HelpPostTitle(discord.ui.Modal, title="Turn into #help post"):
    title_: discord.ui.TextInput[Self] = discord.ui.TextInput(
        label="#help post title", style=discord.TextStyle.short, max_length=100
    )

    def __init__(self, message: discord.Message) -> None:
        super().__init__()
        self._message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        help_channel = cast(
            "discord.ForumChannel", bot.get_channel(config.HELP_CHANNEL_ID)
        )
        await interaction.response.defer(ephemeral=True)

        webhook = await get_or_create_webhook(help_channel)
        msg = await move_message_via_webhook(
            webhook,
            self._message,
            cast("discord.Member", interaction.user),
            thread_name=self.title_.value,
        )
        await (await msg.channel.send(self._message.author.mention)).delete()

        # Apparently msg.channel.mention is unavailable
        await interaction.followup.send(
            content=f"Help post created: <#{msg.channel.id}>", ephemeral=True
        )


class DeleteOriginalMessage(discord.ui.View):
    def __init__(self, message: discord.Message) -> None:
        super().__init__()
        self.message = message

    @discord.ui.button(
        label="Delete instead",
        emoji="🗑️",  # test: allow-vs16
        style=discord.ButtonStyle.danger,
    )
    async def delete(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Self],
    ) -> None:
        button.disabled = True
        await self.message.delete()
        await interaction.response.edit_message(
            content="Deleted the original message.", view=self
        )


class ChooseMessageAction(discord.ui.View):
    attachment_button: discord.ui.Button[Self]
    thread_button: discord.ui.Button[Self]

    def __init__(self, message: MovedMessage) -> None:
        super().__init__()
        self._message = message
        self._add_attachment_button()
        self._add_thread_button()

    @discord.ui.button(label="Delete", emoji="🗑️")  # test: allow-vs16
    async def delete_message(
        self, interaction: discord.Interaction, _button: discord.ui.Button[Self]
    ) -> None:
        await self._message.delete()
        await interaction.response.edit_message(content="Message deleted.", view=None)

    @discord.ui.button(label="Edit via modal", emoji="📝")
    async def send_modal(
        self, interaction: discord.Interaction, _button: discord.ui.Button[Self]
    ) -> None:
        await interaction.response.send_modal(EditMessage(self._message))
        await interaction.delete_original_response()

    def _add_attachment_button(self) -> None:
        match len(self._message.attachments):
            case 0:
                # Don't allow removing attachments when there aren't any.
                pass
            case 1:
                self.attachment_button = discord.ui.Button(
                    label="Remove attachment", emoji="🔗"
                )
                self.attachment_button.callback = self.remove_attachment
                self.add_item(self.attachment_button)
            case _:
                self.attachment_button = discord.ui.Button(
                    label="Remove attachments", emoji="🔗"
                )
                self.attachment_button.callback = self.send_attachment_picker
                self.add_item(self.attachment_button)

    async def remove_attachment(self, interaction: discord.Interaction) -> None:
        await self._message.edit(attachments=[])
        await interaction.response.edit_message(
            content="Attachment removed.", view=None
        )

    async def send_attachment_picker(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content="Select attachments to delete.",
            view=DeleteAttachments(self._message),
        )

    def _add_thread_button(self) -> None:
        self._channel = self._message.channel
        if isinstance(self._channel, discord.Thread):
            # Threads can't have nested threads, try its parent.
            self._channel = self._channel.parent
        if not isinstance(self._channel, discord.TextChannel):
            # Only text channels can have threads.
            return
        self.thread_button = discord.ui.Button(label="Edit in thread", emoji="🧵")
        self.thread_button.callback = self.edit_in_thread
        self.add_item(self.thread_button)

    async def edit_in_thread(self, interaction: discord.Interaction) -> None:
        # Guaranteed by _add_thread_button().
        assert isinstance(self._channel, discord.TextChannel)
        try:
            thread = await self._channel.create_thread(
                name="Edit moved message",
                auto_archive_duration=60,
                reason=f"{interaction.user.name} wants to edit a moved message",
                invitable=False,
            )
        except discord.Forbidden:
            self.thread_button.disabled = True
            await interaction.response.edit_message(content=NO_THREAD_PERMS, view=self)
            raise  # Also log it in Sentry.
        except discord.HTTPException as e:
            if e.code != MAXIMUM_NUMBER_OF_ACTIVE_THREADS_REACHED:
                # None of the other errors are relevant here.
                raise
            self.thread_button.disabled = True
            await interaction.response.edit_message(content=TOO_MANY_THREADS, view=self)
            return
        # Notify the user as soon as possible to prevent the need to defer() to
        # avoid issues on days when the API is slower.
        await interaction.response.edit_message(
            content=f"Created a thread: {thread.mention}.", view=None
        )
        await thread.send(
            f"{interaction.user.mention}, here are the contents of your message:"
        )
        await thread.send(
            self._message.content, allowed_mentions=discord.AllowedMentions.none()
        )
        await thread.send(EDIT_IN_THREAD_HINT)


class EditMessage(discord.ui.Modal, title="Edit Message"):
    new_text: discord.ui.TextInput[Self] = discord.ui.TextInput(
        label="New message content",
        style=discord.TextStyle.long,
        default=discord.utils.MISSING,
        max_length=2000,
    )

    def __init__(self, message: MovedMessage) -> None:
        self.new_text.default = message.content
        super().__init__()
        self._message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._message.edit(
            content=self.new_text.value, allowed_mentions=discord.AllowedMentions.none()
        )
        await interaction.response.send_message("Message edited.", ephemeral=True)


class DeleteAttachments(discord.ui.View):
    select: discord.ui.Select[Self]

    def __init__(self, message: MovedMessage) -> None:
        super().__init__()
        self._message = message
        self.select = discord.ui.Select(
            placeholder="Select attachments", max_values=len(message.attachments)
        )
        for attachment in message.attachments:
            self.select.add_option(
                label=truncate(attachment.title or attachment.filename, 100),
                value=str(attachment.id),
            )
        self.select.callback = self.remove_attachments
        self.add_item(self.select)

    async def remove_attachments(self, interaction: discord.Interaction) -> None:
        to_remove = set(map(int, self.select.values))
        await self._message.edit(
            attachments=[a for a in self._message.attachments if a.id not in to_remove]
        )
        await interaction.response.edit_message(
            content="Attachments removed.", view=None
        )


@bot.tree.context_menu(name="Move message")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.guild_only()
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

    if not message_can_be_moved(message):
        await interaction.response.send_message(
            "System messages cannot be moved.",
            ephemeral=True,
            view=DeleteOriginalMessage(message),
        )
        return

    await interaction.response.send_message(
        "Select a channel to move this message to.",
        view=SelectChannel(message, executor=interaction.user),
        ephemeral=True,
    )


@bot.tree.context_menu(name="Turn into #help post")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.guild_only()
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

    if not message_can_be_moved(message):
        await interaction.response.send_message(
            f"System messages cannot be turned into <#{config.HELP_CHANNEL_ID}> posts.",
            ephemeral=True,
            view=DeleteOriginalMessage(message),
        )
        return

    await interaction.response.send_modal(HelpPostTitle(message))


@bot.tree.context_menu(name="Moved message actions")
@discord.app_commands.guild_only()
async def delete_moved_message(
    interaction: discord.Interaction, message: discord.Message
) -> None:
    assert not is_dm(interaction.user)

    if message.created_at < MOVED_MESSAGE_MODIFICATION_CUTOFF or (
        (moved_message := await MovedMessage.from_message(message))
        is MovedMessageLookupFailed.NOT_FOUND
    ):
        await interaction.response.send_message(
            "This message cannot be modified.", ephemeral=True
        )
        return

    if moved_message is MovedMessageLookupFailed.NOT_MOVED:
        await interaction.response.send_message(
            "This message is not a moved message.", ephemeral=True
        )
        return

    if interaction.user.id != moved_message.original_author_id:
        await interaction.response.send_message(
            "Only the author of a message can modify it.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "What would you like to do?",
        view=ChooseMessageAction(moved_message),
        ephemeral=True,
    )
