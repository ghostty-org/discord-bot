import datetime as dt
from contextlib import suppress
from typing import Self, cast

import discord

from app.setup import bot, config
from app.utils import (
    MAX_ATTACHMENT_SIZE,
    GuildTextChannel,
    MessageData,
    MovedMessage,
    MovedMessageLookupFailed,
    SplitSubtext,
    get_or_create_webhook,
    is_attachment_only,
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

EDIT_METHOD_PROMPT = "What would you like to do?"
MESSAGE_EDIT_HELP = (
    "*Edit via modal* displays a text box that allows you to edit the "
    "contents of your message easily and conveniently. However, Discord's "
    "text box is only intended for plain text, not Discord messages. There is "
    "no Markdown syntax highlighting in this text box, and user or channel "
    "mentions are incredibly difficult to insert or edit. The text box also "
    "covers the entire UI, which makes referencing other messages annoying.\n"
    "\n"
    "*Edit in thread* creates a new private thread, adds you to it, and sends "
    "the message's contents, prompting you to copy it and send an edited "
    "version. This approach is very flexible, as you are using Discord's own "
    "message box to send the edited version of the message. Unfortunately, "
    "since this creates a whole new thread and requires you to copy the "
    "message, it is considerably more cumbersome to use, and requires "
    "considerably more context switching. This is especially annoying on "
    "mobile.\n"
    "\n"
    "**The recommendation** is hence to use *Edit via modal* for editing "
    "small to medium length messages with minimal Markdown and when you are "
    "not touching emojis or channel/user mentions, and *Edit in thread* in "
    "all other cases."
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
NO_CONTENT_TO_EDIT = (
    "{}, your message does not currently have any content. Sending a message "
    "would add the specified content to the message. Any attachments you "
    "upload are also added to your message."
)
EDIT_IN_THREAD_HINT = (
    "Please send a message containing the message's new content.\n"
    "-# **Hint:** you can copy your message's content by pressing "
    '"Copy Text" in the context menu. Any attachments you upload are '
    "also added to your message."
)
NEW_CONTENT_TOO_LONG = (
    "⚠️ Your message is too long! Please try again.\n"  # test: allow-vs16
    "-# **Hint:** the maximum number of characters you can enter is "
    "**{limit}** to account for the subtext, while your message is {length} "
    "characters long, which is **{difference} too many**."
)
TOO_MANY_ATTACHMENTS = (
    "⚠️ Your message contains too many attachments! Please remove "  # test: allow-vs16
    "at least {num_over_limit}.\n"
    "-# **Hint:** you can only add {remaining_slots} more."
)
ATTACHMENTS_TOO_LARGE = (
    "⚠️ Some of your attachments are too large! The following "  # test: allow-vs16
    "attachments exceed the limit of 64 MiB:\n"
    "{offenders}\n"
    "Please try again without those attachments, or press *Skip* to continue "
    "without the offending attachments."
)
NO_ATTACHMENTS_LEFT = (
    "Every attachment was selected, but your message only contains "
    "attachments, which would make the message empty. Would you like to "
    "delete your message instead?"
)
UPLOADING = "⌛ Uploading attachments (this may take some time)…"


# A dictionary mapping threads to the message to edit and the subtext.
edit_threads: dict[int, tuple[MovedMessage, str]] = {}


async def remove_edit_thread(
    thread: discord.Thread,
    author: discord.User | discord.Member,
    *,
    action: str = "finished editing",
) -> None:
    # Suppress NotFound and KeyError to prevent an exception thrown if the user
    # attempts to remove the edit thread through multiple means (such as the
    # cancel button and sending an edited message) at the same time.
    with suppress(discord.NotFound, KeyError):
        await thread.delete(reason=f"{author.name} {action} a moved message")
        del edit_threads[thread.id]


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

    @discord.ui.button(label="Ghostping", emoji="👻")
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


class DeleteInstead(discord.ui.View):
    def __init__(self, message: discord.Message) -> None:
        super().__init__()
        self.message = message

    @discord.ui.button(label="Delete instead", emoji="❌")
    async def delete(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[Self],
    ) -> None:
        button.disabled = True
        await self.message.delete()
        await interaction.response.edit_message(view=self)


class ChooseMessageAction(discord.ui.View):
    attachment_button: discord.ui.Button[Self]
    thread_button: discord.ui.Button[Self]
    help_button: discord.ui.Button[Self]

    def __init__(self, message: MovedMessage) -> None:
        super().__init__()
        self._message = message
        self._split_subtext = SplitSubtext(message)
        self._attachment_button_added = False
        # Adding the thread button might also add the attachment button so that
        # the attachment button can be placed in between the thread and help
        # buttons.
        self._add_thread_button()
        if not self._attachment_button_added:
            self._add_attachment_button()

    @discord.ui.button(label="Delete", emoji="❌")
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
        self._attachment_button_added = True
        match len(self._message.attachments):
            case 0:
                # Don't allow removing attachments when there aren't any.
                pass
            case 1 if is_attachment_only(
                self._message, preprocessed_content=self._split_subtext.content
            ):
                # Don't allow removing the attachment of a message with only
                # one attachment, as that would make the message empty. This is
                # in line with Discord's UI (it does not show the remove button
                # on the attachment if there is only one).
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
            view=DeleteAttachments(
                self._message, preprocessed_content=self._split_subtext.content
            ),
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
        # Add the attachment button here so that it goes in between the thread
        # and help buttons. __init__() guards against this to avoid adding
        # a second attachment button too.
        self._add_attachment_button()
        # Add the help button conditionally as the help text does not make
        # sense without the thread button's presence.
        self.help_button = discord.ui.Button(
            label="Help",
            emoji="ℹ️",  # test: allow-vs16 # noqa: RUF001
        )
        self.help_button.callback = self.show_help
        self.add_item(self.help_button)

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
        if self._split_subtext.content:
            await thread.send(
                f"{interaction.user.mention}, here are the contents of your message:"
            )
            await thread.send(
                self._split_subtext.content,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await thread.send(EDIT_IN_THREAD_HINT, view=CancelEditing(thread))
        else:
            await thread.send(
                NO_CONTENT_TO_EDIT.format(interaction.user.mention),
                view=CancelEditing(thread),
            )
        edit_threads[thread.id] = (self._message, self._split_subtext.format())

    async def show_help(self, interaction: discord.Interaction) -> None:
        self.help_button.disabled = True
        await interaction.response.edit_message(
            content=f"{MESSAGE_EDIT_HELP}\n\n{EDIT_METHOD_PROMPT}", view=self
        )


class EditMessage(discord.ui.Modal, title="Edit Message"):
    new_text: discord.ui.TextInput[Self] = discord.ui.TextInput(
        label="New message content",
        style=discord.TextStyle.long,
        default=discord.utils.MISSING,
    )

    def __init__(self, message: MovedMessage) -> None:
        split_subtext = SplitSubtext(message)
        self._subtext = split_subtext.format()
        self.new_text.default = split_subtext.content
        # Subtract one to account for the newline character.
        self.new_text.max_length = 2000 - len(self._subtext) - 1
        super().__init__()
        self._message = message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._message.edit(
            content=f"{self.new_text.value}\n{self._subtext}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.response.send_message("Message edited.", ephemeral=True)


class DeleteAttachments(discord.ui.View):
    select: discord.ui.Select[Self]

    def __init__(
        self, message: MovedMessage, *, preprocessed_content: str | None = None
    ) -> None:
        super().__init__()
        self._message = message
        self._content = preprocessed_content
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
        remaining = [a for a in self._message.attachments if a.id not in to_remove]
        if not remaining and is_attachment_only(
            self._message, preprocessed_content=self._content
        ):
            await interaction.response.edit_message(
                content=NO_ATTACHMENTS_LEFT, view=DeleteInstead(self._message)
            )
            return
        await self._message.edit(attachments=remaining)
        await interaction.response.edit_message(
            content="Attachments removed.", view=None
        )


class CancelEditing(discord.ui.View):
    def __init__(self, thread: discord.Thread) -> None:
        super().__init__()
        self._thread = thread

    @discord.ui.button(label="Cancel", emoji="❌")
    async def cancel_editing(
        self, interaction: discord.Interaction, _button: discord.ui.Button[Self]
    ) -> None:
        # For some reason, depending on how long deleting the thread takes, the
        # user still sees "Something went wrong." momentarily before the thread
        # is deleted; it's probably dependent on internet speeds. Hence, defer
        # the response to increase the error timeout from five seconds to five
        # minutes so that the user never sees "Something went wrong." before
        # the thread is gone and the user is moved out of the thread.
        await interaction.response.defer()
        await remove_edit_thread(
            self._thread, interaction.user, action="canceled editing of"
        )
        # We can't actually followup on the deferred response here because
        # doing so would result in NotFound being thrown since the thread was
        # just deleted above.


class SkipLargeAttachments(discord.ui.View):
    def __init__(
        self, message: discord.Message, moved_message: MovedMessage, new_content: str
    ) -> None:
        super().__init__()
        self._message = message
        self._moved_message = moved_message
        self._new_content = new_content

    @discord.ui.button(label="Skip", emoji="⏩")
    async def skip_large_attachments(
        self, interaction: discord.Interaction, button: discord.ui.Button[Self]
    ) -> None:
        button.disabled = True
        await interaction.response.edit_message(content=UPLOADING, view=self)
        await self._moved_message.edit(
            content=self._new_content,
            attachments=[
                *self._moved_message.attachments,
                *(await MessageData.scrape(self._message)).files,
            ],
            allowed_mentions=discord.AllowedMentions.none(),
        )
        assert isinstance(self._message.channel, discord.Thread)
        await remove_edit_thread(self._message.channel, self._message.author)


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
            view=DeleteInstead(message),
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
            view=DeleteInstead(message),
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
        EDIT_METHOD_PROMPT, view=ChooseMessageAction(moved_message), ephemeral=True
    )


async def check_for_edit_response(message: discord.Message) -> None:
    if not (
        # While the channel_type check covers this isinstance() check, Pyright
        # needs this isinstance() check to know that the type is definitely
        # a Thread.
        isinstance(message.channel, discord.Thread)
        and message.channel.type is discord.ChannelType.private_thread
        and message.channel.id in edit_threads
    ):
        return

    moved_message, subtext = edit_threads[message.channel.id]

    new_content = "\n".join(filter(None, (message.content, subtext)))
    if len(new_content) > 2000:
        # Subtract one to account for the newline character.
        max_length = 2000 - len(subtext) - 1
        content_length = len(message.content)
        await message.reply(
            NEW_CONTENT_TOO_LONG.format(
                limit=max_length,
                length=content_length,
                difference=content_length - max_length,
            )
        )
        return

    num_existing_attachments = len(moved_message.attachments)
    num_attachments = num_existing_attachments + len(message.attachments)
    if num_attachments > 10:
        await message.reply(
            TOO_MANY_ATTACHMENTS.format(
                num_over_limit=num_attachments - 10,
                remaining_slots=10 - num_existing_attachments,
            )
        )
        return
    # While an alternative would be to make MessageData store the names of all
    # skipped attachments, that would mean that all other attachments would
    # have to be downloaded as well for no reason, so replicate the attachment
    # size check here to avoid downloading anything if even a single attachment
    # is too large.
    if too_large := [a for a in message.attachments if a.size > MAX_ATTACHMENT_SIZE]:
        offenders = "\n".join(
            # HACK: replace all backticks with reverse primes to avoid
            # incorrect rendering of file names that preemptively end the
            # Markdown inline code.
            f"* `{truncate((a.title or a.filename).replace('`', '\u2035'), 100)}`"
            for a in too_large
        )
        await message.reply(
            ATTACHMENTS_TOO_LARGE.format(offenders=offenders),
            view=SkipLargeAttachments(message, moved_message, new_content),
        )
        return

    if message.attachments:
        await message.reply(UPLOADING, mention_author=False)
    await moved_message.edit(
        content=new_content,
        attachments=[
            *moved_message.attachments,
            *(await MessageData.scrape(message)).files,
        ],
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await remove_edit_thread(message.channel, message.author)
