import discord
import textwrap

from app.setup import bot
from app.utils import is_dm, is_mod, server_only_warning


@bot.tree.command(
    name="create-thread", description="Create a thread and move user messages to it."
)
async def create_thread(
    interaction: discord.Interaction,
    title: str,
    starting_message_id: str | None = None,
    ending_message_id: str | None = None,
    ommitted_messages: str = "",
) -> None:
    """
    Create a thread and move user messages to it. (Note: this command only searches within the last 100 messages)

    This can only be invoked by a mod.

    Parameters:
    title: The title of the thread to be created
    starting_message_id: The ID of the message to start the thread from
    ending_message_id: The ID of the message to end the thread at
    ommitted_messages: A comma-separated list of message IDs to be ommitted from the thread
    """
    # Check if the command is run from the Ghostty server
    if is_dm(interaction.user):
        await server_only_warning(interaction)
        return

    # Verify the author is a mod
    if not is_mod(interaction.user):
        await interaction.response.send_message(
            "You do not have permission to use the create-thread command.",
            ephemeral=True,
        )
        return

    # Grab current channel from interaction and create thread
    channel = interaction.channel
    thread = await channel.create_thread(name=title)
    await interaction.response.defer(thinking=True, ephemeral=True)

    # if starting and ending message IDs are provided, move messages between them inclusive to the thread
    if starting_message_id is not None and ending_message_id is not None:
        webhook = await get_webhook(channel)
        starting_message = await channel.fetch_message(int(starting_message_id))
        ending_message = await channel.fetch_message(int(ending_message_id))
        ommitted_ids = ommitted_messages.split(",")
        message_list = []  # keep track of messages to be checked and potentially sent to the thread
        added_messages_dict = {}  # keep track of messages added to the thread
        authors_mentioned = []  # keep track of authors mentioned in the thread

        # append all messages between starting and ending message inclusive
        message_list.append(starting_message)
        async for message in channel.history(
            limit=100, before=ending_message, after=starting_message
        ):
            message_list.append(message)
        message_list.append(ending_message)

        # send messages to thread
        for message in message_list:
            # ignore messages from bot and messages that are requested to be ommitted
            if message.author == bot.user:
                continue
            if str(message.id) in ommitted_ids:
                continue
            # check if message is a reply to a message in the thread or outside of the thread
            if message.reference is not None:
                reference = added_messages_dict.get(message.reference.message_id)
                if reference is None:
                    reference = await channel.fetch_message(
                        message.reference.message_id
                    )
                content = f"> -# **Replying to**: {reference.jump_url}\n> -# {textwrap.shorten(reference.content, width=30)}\n{message.content}"
                await webhook.send(
                    content,
                    username=message.author.name,
                    avatar_url=message.author.avatar.url,
                    thread=thread,
                )
            # if message is not a reply just send it normally
            else:
                await webhook.send(
                    message.content,
                    username=message.author.name,
                    avatar_url=message.author.avatar.url,
                    thread=thread,
                )
            # save the message in case it's a reference to another message in the thread
            sent_message = None
            async for single_message in thread.history(limit=1):
                sent_message = single_message
            added_messages_dict[message.id] = sent_message
            # in the case we have not "ghosted" the author, send a notifying message to the thread and delete it
            if message.author.id not in authors_mentioned:
                authors_mentioned.append(message.author.id)
                notification_message = await thread.send(f"{message.author.mention}")
                await notification_message.delete()
        await interaction.edit_original_response(
            content=f"Thread created: {thread.mention}",
            view=ThreadOptionsView(thread, message_list, interaction, channel),
        )
    else:
        await interaction.delete_original_response()
        await channel.send(f"Thread created: {thread.mention}")


async def get_webhook(channel: discord.TextChannel) -> discord.Webhook:
    # check if a webhook is created for the given channel
    webhooks = await channel.webhooks()
    webhook = None
    if isinstance(webhooks, list):
        for hook in webhooks:
            if hook.name == "Ghostty Thread Creator":
                webhook = hook
                break
    # if no webhook is found, create one
    if webhook is None:
        webhook = await channel.create_webhook(name="Ghostty Thread Creator")
    return webhook


class ThreadOptionsView(discord.ui.View):
    """The view shown to create a thread."""

    def __init__(
        self,
        thread: discord.Thread,
        message_list: list = [],
        bot_interaction: discord.Interaction = None,
        channel: discord.TextChannel = None,
    ) -> None:
        super().__init__(timeout=None)
        self.thread = thread
        self.message_list = message_list
        self.bot_interaction = bot_interaction
        self.channel = channel
        self.omissions = []

    @discord.ui.button(
        label="Delete Original Posts",
        style=discord.ButtonStyle.danger,
        custom_id="delete-original-posts",
    )
    async def delete_original_posts(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.bot_interaction.edit_original_response(
            content="Deleting original posts...", view=None
        )
        for message in self.message_list:
            await message.delete()
        await self.end_prompt()

    @discord.ui.button(
        label="Don't Delete Original Posts",
        style=discord.ButtonStyle.secondary,
        custom_id="dont-delete-original-posts",
    )
    async def dont_delete_original_posts(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.end_prompt()

    async def end_prompt(self) -> None:
        await self.bot_interaction.delete_original_response()
        await self.channel.send(f"Thread created: {self.thread.mention}")
