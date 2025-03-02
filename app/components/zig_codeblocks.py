from __future__ import annotations

import re
from io import BytesIO
from itertools import zip_longest

import discord
from zig_codeblocks import (
    DEFAULT_THEME,
    extract_codeblocks,
    highlight_zig_code,
    process_markdown,
)

from app.utils import (
    MessageLinker,
    get_or_create_webhook,
    is_dm,
    is_mod,
    move_message_via_webhook,
    remove_view_after_timeout,
)

MAX_CONTENT = 51_200  # 50 KiB
MAX_ZIG_FILE_SIZE = 8_388_608  # 8 MiB
VIEW_TIMEOUT = 60.0

SGR_PATTERN = re.compile(r"\x1b\[[0-9;]+m")
THEME = DEFAULT_THEME.copy()
del THEME["comments"]

codeblock_linker = MessageLinker()
frozen_messages = set[discord.Message]()


def process_discord_markdown(source: str | bytes, *, only_code: bool = False) -> str:
    return (
        process_markdown(source, THEME, only_code=only_code)
        # From Qwerasd:
        #   Oh is it a safeguard against catastrophic backtracking?
        #   [...]
        #   I got distracted and checked the Discord source and this is the logic,
        #   highlighting is disabled under these circumstances:
        #   * The src contains 15 or more consecutive slashes
        #   * The src contains a line with 1000 or more characters
        #   * The src contains more than 30 slashes with anything in between as long as
        #     it's not a line that isn't in the form ^\s*\/\/.* and contains a character
        #     other than /
        # These replace calls are an attempt to work around these limitations.
        .replace("///", "\x1b[0m///")
        .replace("// ", "\x1b[0m// ")
    )


class ZigCodeblockActions(discord.ui.View):
    def __init__(self, message: discord.Message) -> None:
        super().__init__()
        self._message = message
        self._replaced_message_content = process_discord_markdown(message.content)
        self.replace.disabled = (
            len(codeblock_linker.get(message)) > 1
            or len(self._replaced_message_content) > 2000
            or len(message.attachments) > 0
        )

    async def _reject_early(
        self, interaction: discord.Interaction, message: str
    ) -> bool:
        assert not is_dm(interaction.user)
        if interaction.user.id == self._message.author.id or is_mod(interaction.user):
            return False
        await interaction.response.send_message(message, ephemeral=True)
        return True

    @discord.ui.button(
        label="Dismiss",
        emoji="❌",
        style=discord.ButtonStyle.gray,
    )
    async def dismiss(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[ZigCodeblockActions],
    ) -> None:
        if await self._reject_early(interaction, "You can't dismiss this message."):
            return
        for reply in codeblock_linker.get(self._message):
            await reply.delete()

    @discord.ui.button(
        label="Freeze",
        emoji="❄️",
        style=discord.ButtonStyle.gray,
    )
    async def freeze(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[ZigCodeblockActions],
    ) -> None:
        if await self._reject_early(interaction, "You can't freeze this message."):
            return

        frozen_messages.add(self._message)
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            "Message frozen. I will no longer react to"
            " what happens to your original message.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Replace my message",
        emoji="🔄",
        style=discord.ButtonStyle.gray,
    )
    async def replace(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[ZigCodeblockActions],
    ) -> None:
        if await self._reject_early(interaction, "You can't use this action."):
            return

        assert interaction.message
        channel = interaction.message.channel
        webhook_channel, thread = (
            (channel.parent, channel)
            if isinstance(channel, discord.Thread)
            else (channel, discord.utils.MISSING)
        )
        assert isinstance(webhook_channel, discord.TextChannel | discord.ForumChannel)

        webhook = await get_or_create_webhook("Ghostty Moderator", webhook_channel)
        self._message.content = self._replaced_message_content
        await move_message_via_webhook(webhook, self._message, thread=thread)


async def _prepare_reply(
    message: discord.Message,
) -> tuple[list[str], list[discord.File]]:
    attachments: list[discord.File] = []
    for att in message.attachments:
        if not att.filename.endswith(".zig") or att.size > MAX_ZIG_FILE_SIZE:
            continue
        content = (await att.read())[:MAX_CONTENT]
        if content.count(b"\n") <= 5 and len(content) <= 1900:
            message.content = f"```zig\n{content.decode()}```\n{message.content}"
            continue
        attachments.append(
            discord.File(
                BytesIO(highlight_zig_code(content, THEME).encode()),
                att.filename + ".ansi",
            )
        )

    codeblocks = list(extract_codeblocks(message.content))
    file_highlight_note = 'Click "View whole file" to see the highlighting.'
    if codeblocks and any(block.lang == "zig" for block in codeblocks):
        zig_code = process_discord_markdown(message.content, only_code=True)
        zig_code += f"\n{file_highlight_note}" if attachments else ""
        return _split_codeblocks(zig_code), attachments
    if attachments:
        return [file_highlight_note], attachments
    return [], []


async def check_for_zig_code(message: discord.Message) -> None:
    msg_contents, files = await _prepare_reply(message)
    if not (msg_contents or files):
        return

    if len(msg_contents) == 1:
        reply = await message.reply(
            msg_contents[0],
            view=ZigCodeblockActions(message),
            files=files,
            mention_author=False,
        )
        codeblock_linker.link(message, reply)
        await remove_view_after_timeout(reply, VIEW_TIMEOUT)
        return

    first_msg = await message.reply(msg_contents[0], mention_author=False)
    codeblock_linker.link(message, first_msg)

    for msg_content in msg_contents[1:-1]:
        msg = await message.channel.send(msg_content)
        codeblock_linker.link(message, msg)

    final_msg = await message.channel.send(
        msg_contents[-1], view=ZigCodeblockActions(message), files=files
    )
    codeblock_linker.link(message, final_msg)
    await remove_view_after_timeout(final_msg, VIEW_TIMEOUT)


async def zig_codeblock_edit_handler(
    before: discord.Message, after: discord.Message
) -> None:
    if before.content == after.content and before.attachments == after.attachments:
        return

    old_contents, old_files = await _prepare_reply(before)
    new_contents, new_files = await _prepare_reply(after)
    if old_contents == new_contents and old_files == new_files:
        return

    if not (replies := codeblock_linker.get(before)):
        if not (old_contents or before in frozen_messages):
            # There was no code before, so treat this as a new message.
            # Note: No new attachments can appear, their count can only decrease.
            await check_for_zig_code(after)
        # The message was removed from the M2C map at some point
        return

    if not (new_contents or new_files or before in frozen_messages):
        # All code was edited out
        codeblock_linker.unlink(before)
        for reply in replies:
            await reply.delete()
        return

    if codeblock_linker.unlink_if_expired(replies[0]):
        frozen_messages.discard(before)
        return

    if before in frozen_messages:
        return

    saved_msg: discord.Message | None = None
    for reply, new_content in zip_longest(replies, new_contents, fillvalue=None):
        if not (reply is None or new_content is None):
            if new_content is new_contents[-1] and len(replies) >= len(new_contents):
                view = ZigCodeblockActions(after)
                files = new_files
            else:
                view = None
                files = discord.utils.MISSING
            await reply.edit(
                content=new_content,
                view=view,
                attachments=files,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            if view is not None:
                saved_msg = reply
            continue
        if reply is None:
            # Out of replies, codeblocks still left -> Create new replies
            if new_content is new_contents[-1]:
                # Last new reply
                msg = await after.channel.send(
                    new_content,
                    view=ZigCodeblockActions(after),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                saved_msg = msg
            else:
                # Not the last new reply
                msg = await after.channel.send(
                    new_content, allowed_mentions=discord.AllowedMentions.none()
                )
            codeblock_linker.link(after, msg)
        else:
            # Out of codeblocks, replies still left -> Delete remaining replies
            await reply.delete()
    if saved_msg is not None:
        await remove_view_after_timeout(saved_msg, VIEW_TIMEOUT)


async def zig_codeblock_delete_handler(message: discord.Message) -> None:
    if message.author.bot and (
        original := codeblock_linker.get_original_message(message)
    ):
        frozen_messages.discard(original)
        replies = codeblock_linker.get(original)
        replies.remove(message)
        if not replies:
            codeblock_linker.unlink(original)
    elif (replies := codeblock_linker.get(message)) and message not in frozen_messages:
        for reply in replies:
            await reply.delete()
        codeblock_linker.unlink(message)
    frozen_messages.discard(message)


def _split_codeblocks(code: str) -> list[str]:
    if len(code) <= 2000:
        return [code]

    def copy_last_style_to_new_part() -> None:
        if SGR_PATTERN.fullmatch(part[1]):
            part[2] = f"{part.pop(1)}{part[2]}"

    lines = code.splitlines()
    parts: list[str] = []
    part: list[str] = []

    while lines:
        # Keep throwing in lines until under the limit
        if len("\n".join(part)) + len(lines[0]) + 4 < 2000:  # 4 = len("\n```")
            part.append(lines.pop(0))
            continue

        # Making sure we're not ending a part in a code block boundary
        if part[-1].startswith("```"):
            lines.insert(0, part.pop())
            if part[-1] == "```ansi":
                lines.insert(0, part.pop())

        copy_last_style_to_new_part()
        parts.append(joined := "\n".join((*part, "```")))
        part = ["```ansi"]

        # Apply last style from previous part to new part
        if styles := SGR_PATTERN.findall(joined):
            part.append(styles.pop())

    # Add unfinished part
    if part:
        copy_last_style_to_new_part()
        parts.append("\n".join(part))

    return parts
