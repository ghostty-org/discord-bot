import asyncio
import datetime as dt
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast, final, override

import discord as dc
from discord.ext import commands

from app.common.message_moving import (
    MovedMessage,
    MovedMessageLookupFailed,
    SplitSubtext,
    convert_nitro_emojis,
    get_or_create_webhook,
    message_can_be_moved,
    move_message,
)
from app.errors import SafeModal, SafeView
from app.utils import (
    MAX_ATTACHMENT_SIZE,
    GuildTextChannel,
    MessageData,
    dynamic_timestamp,
    is_attachment_only,
    is_dm,
    safe_edit,
    truncate,
)

if TYPE_CHECKING:
    from app.bot import GhosttyBot
    from app.utils import Account


# From https://discord.com/developers/docs/topics/opcodes-and-status-codes#json-json-error-codes.
_MAXIMUM_NUMBER_OF_ACTIVE_THREADS_REACHED = 160006

_MOVED_MESSAGE_MODIFICATION_CUTOFF = dt.datetime(
    year=2025, month=6, day=18, hour=23, minute=10, tzinfo=dt.UTC
)

_EDIT_METHOD_PROMPT = "What would you like to do?"
_MESSAGE_EDIT_HELP = (
    "*Edit via modal* displays a text box that allows you to edit the contents of your "
    "message easily and conveniently. However, Discord's text box is only intended for "
    "plain text, not Discord messages. There is no Markdown syntax highlighting in "
    "this text box, and user or channel mentions are incredibly difficult to insert or "
    "edit. The text box also covers the entire UI, which makes referencing other "
    "messages annoying.\n"
    "\n"
    "*Edit in thread* creates a new private thread, adds you to it, and sends the "
    "message's contents, prompting you to copy it and send an edited version. This "
    "approach is very flexible, as you are using Discord's own message box to send the "
    "edited version of the message. Unfortunately, since this creates a whole new "
    "thread and requires you to copy the message, it is considerably more cumbersome "
    "to use, and requires considerably more context switching. This is especially "
    "annoying on mobile.\n"
    "\n"
    "**The recommendation** is hence to use *Edit via modal* for editing small to "
    "medium length messages with minimal Markdown and when you are not touching emojis "
    "or channel/user mentions, and *Edit in thread* in all other cases."
)
_ALREADY_EDITING = (
    "You are already editing a message in a thread! You can only edit one message in "
    "a thread at a time, to prevent abuse. Please finish editing the message at "
    "<#{thread_id}> first, or use the modal."
)
_NO_THREAD_PERMS = (
    "⚠️ I don't have the required permissions to create private "  # test: allow-vs16
    "threads; please contact a moderator! In the meantime, use the modal instead."
)
_TOO_MANY_THREADS = (
    "⚠️ There are too many active threads in this server! Use the "  # test: allow-vs16
    "modal instead, or try again later."
)
_NO_CONTENT_TO_EDIT = (
    "{}, your message does not currently have any content. Sending a message would add "
    "the specified content to the message. Any attachments you upload are also added "
    "to your message."
)
_EDIT_IN_THREAD_HINT = (
    "Please send a message containing the message's new content.\n"
    "-# **Hint:** you can copy your message's content by pressing "
    '"Copy Text" in the context menu. Any attachments you upload are '
    "also added to your message."
)
_NEW_CONTENT_TOO_LONG = (
    "⚠️ Your message is too long! Please try again.\n"  # test: allow-vs16
    "-# **Hint:** the maximum number of characters you can enter is **{limit}** to "
    "account for the subtext, while your message is {length} characters long, which is "
    "**{difference} too many**."
)
_TOO_MANY_ATTACHMENTS = (
    "⚠️ Your message contains too many attachments! Please remove "  # test: allow-vs16
    "at least {num_over_limit}.\n"
    "-# **Hint:** you can only add {remaining_slots} more."
)
_ATTACHMENTS_TOO_LARGE = (
    "⚠️ Some of your attachments are too large! The following "  # test: allow-vs16
    "attachments exceed the limit of 64 MiB:\n"
    "{offenders}\n"
    "Please try again without those attachments, or press *Skip* to continue without "
    "the offending attachments."
)
_ALL_ATTACHMENTS_TOO_LARGE = (
    "⚠️ All of your attachments are too large! The limit for the "  # test: allow-vs16
    "size of attachments is 64 MiB. Please try again with smaller attachments."
)
_NO_ATTACHMENTS_LEFT = (
    "Every attachment was selected, but your message only contains attachments, which "
    "would make the message empty. Would you like to delete your message instead?"
)
_ATTACHMENTS_ONLY = (
    "Your new message only contains attachments! Doing so will result in your "
    "message's previous content being removed. Is that what you meant to do?"
)
_EDITING_TIMEOUT_ALMOST_REACHED = (
    "{}, are you still editing this message? This thread will be deleted "
    "{in_five_minutes} if it remains inactive."
)
_UPLOADING = "⌛ Uploading attachments (this may take some time)…"


@final
class DeleteInstead(SafeView):
    def __init__(self, message: dc.Message) -> None:
        super().__init__()
        self.message = message

    @dc.ui.button(label="Delete instead", emoji="❌")
    async def delete(
        self, interaction: dc.Interaction, button: dc.ui.Button[Self]
    ) -> None:
        button.disabled = True
        await self.message.delete()
        await interaction.response.edit_message(view=self)


@dataclass
class ThreadState:
    moved_message: MovedMessage
    split_subtext: SplitSubtext
    last_update: dt.datetime


@final
class SelectChannel(SafeView):
    def __init__(
        self, bot: GhosttyBot, message: dc.Message, executor: dc.Member
    ) -> None:
        super().__init__()
        self.bot = bot
        self.message = message
        self.executor = executor

    @dc.ui.select(
        cls=dc.ui.ChannelSelect,
        channel_types=[dc.ChannelType.text, dc.ChannelType.public_thread],
        placeholder="Select a channel",
        min_values=1,
        max_values=1,
    )
    async def select_channel(
        self, interaction: dc.Interaction, sel: dc.ui.ChannelSelect[Self]
    ) -> None:
        channel = await self.bot.fetch_channel(sel.values[0].id)
        assert isinstance(channel, GuildTextChannel)
        if channel.id == self.message.channel.id:
            await interaction.response.edit_message(
                content=(
                    "You can't move a message to the same channel. "
                    "Pick a different channel."
                )
            )
            return

        await interaction.response.defer()
        webhook_channel, thread = (
            (channel.parent, channel)
            if isinstance(channel, dc.Thread)
            else (channel, dc.utils.MISSING)
        )
        assert isinstance(webhook_channel, dc.TextChannel | dc.ForumChannel)

        webhook = await get_or_create_webhook(webhook_channel)
        moved_message = await move_message(
            self.bot, webhook, self.message, self.executor, thread=thread
        )
        await interaction.edit_original_response(
            content=f"Moved the message to {channel.mention}.",
            view=Ghostping(moved_message.original_author_id, channel),
        )


@final
class Ghostping(SafeView):
    def __init__(self, author: dc.Member | int, channel: GuildTextChannel) -> None:
        """
        Don't forget to use a returned MovedMessage's original author if applicable, so
        as to correctly handle ghostpings on moved moved messages!
        """
        # An ID is allowed too instead of a full Member as MovedMessages don't normally
        # have an author attached. While this view would normally only be used after
        # moving a message, and move_message() does cache the author in the
        # MovedMessage, assuming that behavior can lead to a reduction in performance in
        # the future if that behavior is changed, as there is no indication that this
        # function needs to be updated were that done.
        super().__init__()
        self._author_id = author.id if isinstance(author, dc.Member) else author
        self._channel = channel

    @dc.ui.button(label="Ghostping", emoji="👻")
    async def ghostping(
        self, interaction: dc.Interaction, button: dc.ui.Button[Self]
    ) -> None:
        button.disabled = True
        mention = f"<@{self._author_id}>"
        await interaction.response.edit_message(
            content=(
                f"Moved the message to {self._channel.mention} "
                f"and ghostpinged {mention}."
            ),
            view=self,
            allowed_mentions=dc.AllowedMentions.none(),
        )
        await (await self._channel.send(mention)).delete()


@final
class HelpPostTitle(SafeModal, title="Turn into #help post"):
    title_ = dc.ui.TextInput[Self](
        label="#help post title", style=dc.TextStyle.short, max_length=100
    )

    def __init__(self, bot: GhosttyBot, message: dc.Message) -> None:
        super().__init__()
        self.bot = bot
        self._message = message

    @override
    async def on_submit(self, interaction: dc.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        webhook = await get_or_create_webhook(self.bot.help_channel)
        msg = await move_message(
            self.bot,
            webhook,
            self._message,
            cast("dc.Member", interaction.user),
            thread_name=self.title_.value,
        )
        await (await msg.channel.send(f"<@{msg.original_author_id}>")).delete()

        # Apparently msg.channel.mention is unavailable
        await interaction.followup.send(
            content=f"Help post created: <#{msg.channel.id}>", ephemeral=True
        )


@final
class ChooseMessageAction(SafeView):
    thread_button: dc.ui.Button[Self]
    help_button: dc.ui.Button[Self]

    def __init__(self, cog: MoveMessage, message: MovedMessage) -> None:
        super().__init__()
        self._cog = cog
        self._message = message
        self._split_subtext = SplitSubtext(message)
        self._attachment_button_added = False
        # Adding the thread button might also add the attachment button so that the
        # attachment button can be placed in between the thread and help buttons.
        self._add_thread_button()
        if not self._attachment_button_added:
            self._add_attachment_button()

    @dc.ui.button(label="Delete", emoji="❌")
    async def delete_message(
        self, interaction: dc.Interaction, _button: dc.ui.Button[Self]
    ) -> None:
        await self._message.delete()
        await interaction.response.edit_message(content="Message deleted.", view=None)

    @dc.ui.button(label="Edit via modal", emoji="📝")
    async def send_modal(
        self, interaction: dc.Interaction, _button: dc.ui.Button[Self]
    ) -> None:
        await interaction.response.send_modal(
            EditMessage(self._cog.bot, self._message, self._split_subtext)
        )
        await interaction.delete_original_response()

    def _add_attachment_button(self) -> None:
        self._attachment_button_added = True
        match len(self._message.attachments):
            case 0:
                # Don't allow removing attachments when there aren't any.
                return
            case 1 if is_attachment_only(
                self._message, preprocessed_content=self._split_subtext.content
            ):
                # Don't allow removing the attachment of a message with only one
                # attachment, as that would make the message empty. This is in line with
                # Discord's UI (it does not show the remove button on the attachment if
                # there is only one).
                return
            case 1:
                label, callback = "Remove attachment", self.remove_attachment
            case _:
                label, callback = "Remove attachments", self.send_attachment_picker

        attachment_button = dc.ui.Button[Self](label=label, emoji="🔗")
        attachment_button.callback = callback
        self.add_item(attachment_button)

    async def remove_attachment(self, interaction: dc.Interaction) -> None:
        await self._message.edit(attachments=[])
        await interaction.response.edit_message(
            content="Attachment removed.", view=None
        )

    async def send_attachment_picker(self, interaction: dc.Interaction) -> None:
        await interaction.response.edit_message(
            content="Select attachments to delete.",
            view=DeleteAttachments(
                self._message, preprocessed_content=self._split_subtext.content
            ),
        )

    def _add_thread_button(self) -> None:
        self._channel = self._message.channel
        if isinstance(self._channel, dc.Thread):
            # Threads can't have nested threads, try its parent.
            self._channel = self._channel.parent
        if not isinstance(self._channel, dc.TextChannel):
            # Only text channels can have threads.
            return
        self.thread_button = dc.ui.Button(label="Edit in thread", emoji="🧵")
        self.thread_button.callback = self.edit_in_thread
        self.add_item(self.thread_button)
        # Add the attachment button here so that it goes in between the thread and help
        # buttons. __init__() guards against this to avoid adding a second attachment
        # button too.
        self._add_attachment_button()
        # Add the help button conditionally as the help text does not make sense without
        # the thread button's presence.
        self.help_button = dc.ui.Button(
            label="Help",
            emoji="ℹ️",  # test: allow-vs16 # noqa: RUF001
        )
        self.help_button.callback = self.show_help
        self.add_item(self.help_button)

    async def edit_in_thread(self, interaction: dc.Interaction) -> None:
        # Guaranteed by _add_thread_button().
        assert isinstance(self._channel, dc.TextChannel)
        existing_thread = self._cog.edit_thread_creators.get(interaction.user.id)
        if existing_thread is not None:
            # While the better solution would be to disable this button upfront and show
            # this message through other means (such as a tooltip), Discord doesn't let
            # you do that :(.
            self.thread_button.disabled = True
            await interaction.response.edit_message(
                content=_ALREADY_EDITING.format(thread_id=existing_thread), view=self
            )
            return
        try:
            thread = await self._channel.create_thread(
                name="Edit moved message",
                auto_archive_duration=60,
                reason=f"{interaction.user.name} wants to edit a moved message",
                invitable=False,
            )
        except dc.Forbidden:
            self.thread_button.disabled = True
            await interaction.response.edit_message(content=_NO_THREAD_PERMS, view=self)
            raise  # Also log it in Sentry.
        except dc.HTTPException as e:
            if e.code != _MAXIMUM_NUMBER_OF_ACTIVE_THREADS_REACHED:
                # None of the other errors are relevant here.
                raise
            self.thread_button.disabled = True
            await interaction.response.edit_message(
                content=_TOO_MANY_THREADS, view=self
            )
            return
        # Notify the user as soon as possible to prevent the need to defer() to avoid
        # issues on days when the API is slower.
        await interaction.response.edit_message(
            content=f"Created a thread: {thread.mention}.", view=None
        )
        if self._split_subtext.content:
            await thread.send(
                f"{interaction.user.mention}, here are the contents of your message:"
            )
            await thread.send(
                self._split_subtext.content, allowed_mentions=dc.AllowedMentions.none()
            )
            await thread.send(
                _EDIT_IN_THREAD_HINT, view=CancelEditing(self._cog, thread)
            )
        else:
            await thread.send(
                _NO_CONTENT_TO_EDIT.format(interaction.user.mention),
                view=CancelEditing(self._cog, thread),
            )
        self._cog.edit_threads[thread.id] = ThreadState(
            self._message, self._split_subtext, dt.datetime.now(tz=dt.UTC)
        )
        self._cog.edit_thread_creators[interaction.user.id] = thread.id
        await self._cog.remove_edit_thread_after_timeout(thread, interaction.user)

    async def show_help(self, interaction: dc.Interaction) -> None:
        self.help_button.disabled = True
        await interaction.response.edit_message(
            content=f"{_MESSAGE_EDIT_HELP}\n\n{_EDIT_METHOD_PROMPT}", view=self
        )


@final
class EditMessage(SafeModal, title="Edit Message"):
    new_text = dc.ui.TextInput[Self](
        label="New message content",
        style=dc.TextStyle.long,
        default=dc.utils.MISSING,
    )

    def __init__(
        self, bot: GhosttyBot, message: MovedMessage, split_subtext: SplitSubtext
    ) -> None:
        super().__init__()
        self.bot = bot
        self._split_subtext = split_subtext
        self.new_text.default = split_subtext.content
        # Subtract one to account for the newline character.
        self.new_text.max_length = 2000 - len(split_subtext.subtext) - 1
        self._message = message

    @override
    async def on_submit(self, interaction: dc.Interaction) -> None:
        content = f"{self.new_text.value}\n{self._split_subtext.subtext}"
        converted_content = convert_nitro_emojis(
            self.bot, self.bot.ghostty_guild, content
        )
        await self._message.edit(
            content=converted_content if len(converted_content) <= 2000 else content,
            allowed_mentions=dc.AllowedMentions.none(),
        )
        await interaction.response.send_message("Message edited.", ephemeral=True)


@final
class DeleteAttachments(SafeView):
    select: dc.ui.Select[Self]

    def __init__(
        self, message: MovedMessage, *, preprocessed_content: str | None = None
    ) -> None:
        super().__init__()
        self._message = message
        self._content = preprocessed_content
        self.select = dc.ui.Select(
            placeholder="Select attachments", max_values=len(message.attachments)
        )
        for attachment in message.attachments:
            self.select.add_option(
                label=truncate(attachment.title or attachment.filename, 100),
                value=str(attachment.id),
            )
        self.select.callback = self.remove_attachments
        self.add_item(self.select)

    async def remove_attachments(self, interaction: dc.Interaction) -> None:
        to_remove = set(map(int, self.select.values))
        remaining = [a for a in self._message.attachments if a.id not in to_remove]
        if not remaining and is_attachment_only(
            self._message, preprocessed_content=self._content
        ):
            await interaction.response.edit_message(
                content=_NO_ATTACHMENTS_LEFT, view=DeleteInstead(self._message)
            )
            return
        await self._message.edit(attachments=remaining)
        await interaction.response.edit_message(
            content=f"Attachment{'s' * (len(to_remove) != 1)} removed.", view=None
        )


@final
class CancelEditing(SafeView):
    def __init__(self, cog: MoveMessage, thread: dc.Thread) -> None:
        super().__init__()
        self._cog = cog
        self._thread = thread

    @dc.ui.button(label="Cancel", emoji="❌")
    async def cancel_editing(
        self, interaction: dc.Interaction, _button: dc.ui.Button[Self]
    ) -> None:
        # For some reason, depending on how long deleting the thread takes, the user
        # still sees "Something went wrong." momentarily before the thread is deleted;
        # it's probably dependent on internet speeds. Hence, defer the response to
        # increase the error timeout from five seconds to five minutes so that the user
        # never sees "Something went wrong." before the thread is gone and the user is
        # moved out of the thread.
        await interaction.response.defer()
        await self._cog.remove_edit_thread(
            self._thread, interaction.user, action="canceled editing of"
        )
        # We can't actually followup on the deferred response here because doing so
        # would result in NotFound being thrown since the thread was just deleted above.


@final
class ContinueEditing(SafeView):
    def __init__(self, cog: MoveMessage, thread: dc.Thread) -> None:
        super().__init__()
        self._cog = cog
        self._thread = thread

    @dc.ui.button(label="Continue Editing", emoji="📜")
    async def continue_editing(
        self, interaction: dc.Interaction, _button: dc.ui.Button[Self]
    ) -> None:
        self._cog.edit_threads[self._thread.id].last_update = dt.datetime.now(tz=dt.UTC)
        assert interaction.message is not None
        await interaction.message.delete()

    @dc.ui.button(label="Cancel Editing", emoji="❌")
    async def cancel_editing(
        self, interaction: dc.Interaction, _button: dc.ui.Button[Self]
    ) -> None:
        # See the comments in CancelEditing.cancel_editing() for the reasoning behind
        # deferring here.
        await interaction.response.defer()
        await self._cog.remove_edit_thread(
            self._thread, interaction.user, action="canceled editing of"
        )


@final
class SkipLargeAttachments(SafeView):
    def __init__(
        self,
        cog: MoveMessage,
        message: dc.Message,
        state: ThreadState,
        new_content: str,
    ) -> None:
        super().__init__()
        self._cog = cog
        self._message = message
        self._state = state
        self._moved_message = state.moved_message
        self._new_content = new_content

    @dc.ui.button(label="Skip", emoji="⏩")
    async def skip_large_attachments(
        self, interaction: dc.Interaction, button: dc.ui.Button[Self]
    ) -> None:
        self._state.last_update = dt.datetime.now(tz=dt.UTC)
        if is_attachment_only(self._message) and not is_attachment_only(
            self._moved_message, preprocessed_content=self._state.split_subtext.content
        ):
            await interaction.response.edit_message(
                content=_ATTACHMENTS_ONLY,
                view=AttachmentChoice(self._cog, self._message, self._state),
            )
            return

        button.disabled = True
        await interaction.response.edit_message(content=_UPLOADING, view=self)
        await self._cog.apply_edit_from_thread(
            self._moved_message, self._message, self._new_content
        )
        assert isinstance(self._message.channel, dc.Thread)
        await self._cog.remove_edit_thread(
            self._message.channel, self._message.author, action="finished editing"
        )


@final
class AttachmentChoice(SafeView):
    def __init__(
        self, cog: MoveMessage, message: dc.Message, state: ThreadState
    ) -> None:
        super().__init__()
        self._cog = cog
        self._message = message
        self._state = state

    @dc.ui.button(label="No, keep content", emoji="📜")
    async def keep(
        self, interaction: dc.Interaction, _button: dc.ui.Button[Self]
    ) -> None:
        await self._edit(interaction, dc.utils.MISSING)

    @dc.ui.button(label="Yes, discard content", emoji="🖼️")  # test: allow-vs16
    async def discard(
        self, interaction: dc.Interaction, _button: dc.ui.Button[Self]
    ) -> None:
        await self._edit(interaction, self._state.split_subtext.subtext)

    async def _edit(self, interaction: dc.Interaction, content: str) -> None:
        self._state.last_update = dt.datetime.now(tz=dt.UTC)
        await interaction.response.edit_message(content=_UPLOADING, view=None)
        await self._cog.apply_edit_from_thread(
            self._state.moved_message, self._message, content
        )
        assert isinstance(self._message.channel, dc.Thread)
        await self._cog.remove_edit_thread(
            self._message.channel, self._message.author, action="finished editing"
        )


@final
class MoveMessage(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

        # A dictionary mapping edit thread IDs to their state. An ID is used instead of
        # the thread itself because there is a thread available already at all places
        # this is used, and because it isn't obvious how threads are hashed.
        self.edit_threads: dict[int, ThreadState] = {}
        # A dictionary mapping edit thread creator IDs to the ID of the thread they are
        # editing in. IDs are used for the same reason as above.
        self.edit_thread_creators: dict[int, int] = {}

        self.context_menus = (
            dc.app_commands.ContextMenu(
                name="Move message",
                callback=self.move_message,
            ),
            dc.app_commands.ContextMenu(
                name="Moved message actions",
                callback=self.moved_message_actions,
            ),
            dc.app_commands.ContextMenu(
                name="Turn into #help post",
                callback=self.turn_into_help_post,
            ),
        )
        for ctx_menu in self.context_menus:
            self.bot.tree.add_command(ctx_menu)

    @override
    async def cog_unload(self) -> None:
        for ctx_menu in self.context_menus:
            self.bot.tree.remove_command(ctx_menu.name, type=ctx_menu.type)

    async def apply_edit_from_thread(
        self,
        moved_message: MovedMessage,
        message: dc.Message,
        new_content: str,
    ) -> None:
        channel = moved_message.channel
        converted_content = convert_nitro_emojis(
            self.bot, self.bot.ghostty_guild, new_content
        )
        if len(converted_content) <= 2000:
            new_content = converted_content
        # Suppress NotFound in case the user attempts to commit an edit to a message
        # that was deleted in the meantime.
        with safe_edit:
            await moved_message.edit(
                content=new_content,
                attachments=[
                    # It is possible that our message to edit is stale if the user
                    # removed an attachment from the message after they started editing
                    # it. Thus, re-fetch the message before grabbing its attachments to
                    # avoid an HTTPException from missing attachments. It is not stored
                    # to a variable beforehand because fetch_message() returns a Message
                    # which can't be used to edit a webhook message, so we use the old
                    # MovedMessage to perform the edit itself.
                    *(await channel.fetch_message(moved_message.id)).attachments,
                    *(await MessageData.scrape(message)).files,
                ],
                allowed_mentions=dc.AllowedMentions.none(),
            )

    async def remove_edit_thread(
        self, thread: dc.Thread, author: Account, *, action: str
    ) -> None:
        # Suppress NotFound and KeyError to prevent an exception thrown if the user
        # attempts to remove the edit thread through multiple means (such as the cancel
        # button and sending an edited message) at the same time.
        with suppress(dc.NotFound, KeyError):
            await thread.delete(reason=f"{author.name} {action} a moved message")
            del self.edit_threads[thread.id]
            del self.edit_thread_creators[author.id]

    async def remove_edit_thread_after_timeout(
        self, thread: dc.Thread, author: Account
    ) -> None:
        # Start off with a last update check so that recursive calls to this function
        # don't need to pass the remaining time around.
        elapsed = dt.datetime.now(tz=dt.UTC) - self.edit_threads[thread.id].last_update
        time_to_warning = dt.timedelta(minutes=10) - elapsed
        # Keep sleeping until we have a zero or negative time to the warning. This has
        # to be a while loop because other coroutines may have touched the last update
        # time of this edit thread while we were sleeping.
        while time_to_warning > dt.timedelta():
            await asyncio.sleep(time_to_warning.total_seconds())
            if thread.id not in self.edit_threads:
                # The user finished or canceled editing of the thread while we were
                # asleep.
                return
            # Re-calculate how much of the timeout has been elapsed to account for the
            # last thread update time once again.
            elapsed = (
                dt.datetime.now(tz=dt.UTC) - self.edit_threads[thread.id].last_update
            )
            time_to_warning = dt.timedelta(minutes=10) - elapsed
        # At this point, we have definitely waited ten minutes from the last thread
        # update, so send a warning to the user.
        remaining = dt.timedelta(minutes=5)
        await thread.send(
            _EDITING_TIMEOUT_ALMOST_REACHED.format(
                author.mention,
                in_five_minutes=dynamic_timestamp(
                    dt.datetime.now(tz=dt.UTC) + remaining, "R"
                ),
            ),
            view=ContinueEditing(self, thread),
        )
        await asyncio.sleep(remaining.total_seconds())
        if thread.id not in self.edit_threads:
            # The user finished or canceled editing of the thread while we were asleep.
            return
        # We once again need to re-calculate how much of the timeout has been elapsed to
        # account for the last thread update time. This is especially important this
        # time around since it's how the "Continue Editing" button signals to us that
        # the user opted to continue.
        elapsed = dt.datetime.now(tz=dt.UTC) - self.edit_threads[thread.id].last_update
        if elapsed >= dt.timedelta(minutes=15):
            # Fifteen minutes (time_to_warning's delta + remaining) have passed, so we
            # shall delete the thread now.
            await self.remove_edit_thread(thread, author, action="abandoned editing of")
            return
        # Restart the wait time. The start of this function will deal with the remaining
        # time left to sleep.
        await self.remove_edit_thread_after_timeout(thread, author)

    # Context menu that is setup in __init__
    @dc.app_commands.default_permissions(manage_messages=True)
    @dc.app_commands.guild_only()
    async def move_message(
        self, interaction: dc.Interaction, message: dc.Message
    ) -> None:
        """
        Adds a context menu item to a message to move it to a different channel. This is
        used as a moderation tool to make discussion on-topic.
        """
        assert not is_dm(interaction.user)

        if not self.bot.is_privileged(interaction.user):
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
            view=SelectChannel(self.bot, message, executor=interaction.user),
            ephemeral=True,
        )

    # Context menu that is setup in __init__
    @dc.app_commands.default_permissions(manage_messages=True)
    @dc.app_commands.guild_only()
    async def turn_into_help_post(
        self, interaction: dc.Interaction, message: dc.Message
    ) -> None:
        """
        An extension of "move message" that creates a #help post and then moves the
        moves the message to that thread.
        """
        assert not is_dm(interaction.user)

        if not self.bot.is_privileged(interaction.user):
            await interaction.response.send_message(
                "You do not have permission to use this action.", ephemeral=True
            )
            return

        if not message_can_be_moved(message):
            await interaction.response.send_message(
                "System messages cannot be turned into "
                f"{self.bot.help_channel.mention} posts.",
                ephemeral=True,
                view=DeleteInstead(message),
            )
            return

        await interaction.response.send_modal(HelpPostTitle(self.bot, message))

    # Context menu that is setup in __init__
    @dc.app_commands.guild_only()
    async def moved_message_actions(
        self, interaction: dc.Interaction, message: dc.Message
    ) -> None:
        assert not is_dm(interaction.user)

        if message.created_at < _MOVED_MESSAGE_MODIFICATION_CUTOFF or (
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
            _EDIT_METHOD_PROMPT,
            view=ChooseMessageAction(self, moved_message),
            ephemeral=True,
        )

    @commands.Cog.listener("on_message")
    async def check_for_edit_response(self, message: dc.Message) -> None:
        if message.author == self.bot.user or not (
            # While the channel_type check covers this isinstance() check, Pyright needs
            # this isinstance() check to know that the type is definitely a Thread.
            isinstance(message.channel, dc.Thread)
            and message.channel.type is dc.ChannelType.private_thread
            and message.channel.id in self.edit_threads
        ):
            return

        state = self.edit_threads[message.channel.id]
        state.last_update = dt.datetime.now(tz=dt.UTC)
        moved_message, split_subtext = state.moved_message, state.split_subtext

        new_content = "\n".join(filter(None, (message.content, split_subtext.subtext)))
        if len(new_content) > 2000:
            # Subtract one to account for the newline character.
            max_length = 2000 - len(split_subtext.subtext) - 1
            content_length = len(message.content)
            await message.reply(
                _NEW_CONTENT_TOO_LONG.format(
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
                _TOO_MANY_ATTACHMENTS.format(
                    num_over_limit=num_attachments - 10,
                    remaining_slots=10 - num_existing_attachments,
                )
            )
            return
        # While an alternative would be to make MessageData store the names of all
        # skipped attachments, that would mean that all other attachments would have to
        # be downloaded as well for no reason, so replicate the attachment size check
        # here to avoid downloading anything if even a single attachment is too large.
        if too_large := [
            a for a in message.attachments if a.size > MAX_ATTACHMENT_SIZE
        ]:
            if len(too_large) == len(message.attachments):
                await message.reply(_ALL_ATTACHMENTS_TOO_LARGE)
                return
            offenders = "\n".join(
                # HACK: replace all backticks with reverse primes to avoid incorrect
                # rendering of file names that preemptively end the Markdown inline code
                f"* `{truncate((a.title or a.filename).replace('`', '\u2035'), 100)}`"
                for a in too_large
            )
            await message.reply(
                _ATTACHMENTS_TOO_LARGE.format(offenders=offenders),
                view=SkipLargeAttachments(self, message, state, new_content),
            )
            return

        if is_attachment_only(message) and not is_attachment_only(
            moved_message, preprocessed_content=split_subtext.content
        ):
            await message.reply(
                _ATTACHMENTS_ONLY, view=AttachmentChoice(self, message, state)
            )
            return

        if message.attachments:
            await message.reply(_UPLOADING, mention_author=False)
        await self.apply_edit_from_thread(moved_message, message, new_content)
        await self.remove_edit_thread(
            message.channel, message.author, action="finished editing"
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(MoveMessage(bot))
