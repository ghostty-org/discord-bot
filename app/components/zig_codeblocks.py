from __future__ import annotations

import re
import string
from io import BytesIO
from random import choices
from typing import TYPE_CHECKING, Self

import discord as dc
from zig_codeblocks import (
    DEFAULT_THEME,
    CodeBlock,
    extract_codeblocks,
    highlight_zig_code,
    process_markdown,
)

from app.common.hooks import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)
from app.common.message_moving import get_or_create_webhook, move_message_via_webhook

if TYPE_CHECKING:
    from collections.abc import Collection

MAX_CONTENT = 51_200  # 50 KiB
MAX_ZIG_FILE_SIZE = 8_388_608  # 8 MiB
FILE_HIGHLIGHT_NOTE = '\nOn desktop, click "View whole file" to see the highlighting.'
OMISSION_NOTE = "\n-# {} codeblock{} omitted"

# This pattern is intentionally simple; it's only meant to operate on sequences produced
# by zig-codeblocks which will never appear in any other form.
SGR_PATTERN = re.compile(r"\x1b\[[0-9;]+m")
THEME = DEFAULT_THEME.copy()
del THEME["Comment"]

codeblock_linker = MessageLinker()
frozen_messages = set[dc.Message]()


def apply_discord_wa(source: str) -> str:
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
    return source.replace("///", "\x1b[0m///").replace("// ", "\x1b[0m// ")


class CodeblockActions(ItemActions):
    linker = codeblock_linker
    action_singular = "sent this code block"
    action_plural = "sent these code blocks"

    def __init__(self, message: dc.Message, item_count: int) -> None:
        super().__init__(message, item_count)
        replaced_content = apply_discord_wa(process_markdown(message.content, THEME))
        if message.attachments or len(replaced_content) > 2000:
            self.replace.disabled = True
        else:
            self._replaced_message_content = replaced_content

    @dc.ui.button(label="Replace my message", emoji="🔄")
    async def replace(self, interaction: dc.Interaction, _: dc.ui.Button[Self]) -> None:
        if await self._reject_early(interaction, "replace"):
            return

        assert interaction.message
        channel = interaction.message.channel
        webhook_channel, thread = (
            (channel.parent, channel)
            if isinstance(channel, dc.Thread)
            else (channel, dc.utils.MISSING)
        )
        assert isinstance(webhook_channel, dc.TextChannel | dc.ForumChannel)

        webhook = await get_or_create_webhook(webhook_channel)
        self.message.content = self._replaced_message_content
        await move_message_via_webhook(
            webhook, self.message, thread=thread, include_move_marks=False
        )


async def _collect_attachments(message: dc.Message) -> list[dc.File]:
    attachments: list[dc.File] = []
    for att in message.attachments:
        if not att.filename.endswith(".zig") or att.size > MAX_ZIG_FILE_SIZE:
            continue
        content = (await att.read())[:MAX_CONTENT]
        if content.count(b"\n") <= 5 and len(content) <= 1900:
            message.content = f"{CodeBlock('zig', content.decode())}\n{message.content}"
            continue
        attachments.append(
            dc.File(
                BytesIO(highlight_zig_code(content, THEME).encode()),
                att.filename + ".ansi",
            )
        )
    return attachments


def _tallest_codeblock_to_file(codeblocks: list[CodeBlock]) -> dc.File:
    tallest_codeblock = max(
        codeblocks,
        key=lambda cb: (len(cb.body.splitlines()), len(cb.body)),
    )
    codeblocks.remove(tallest_codeblock)
    return dc.File(
        BytesIO(tallest_codeblock.body.encode()),
        filename=f"{''.join(choices(string.ascii_letters, k=6))}.ansi",
    )


def _add_user_notes(
    content: str, omitted_codeblocks: int, attachments: Collection[dc.File]
) -> str:
    if attachments:
        content += FILE_HIGHLIGHT_NOTE

    if omitted_codeblocks:
        user_note = OMISSION_NOTE.format(
            omitted_codeblocks, " was" if omitted_codeblocks == 1 else "s were"
        )
        truncation_size = 2000 - len(user_note) - 1  # -1 for the ellipsis
        if attachments:
            content = content.removesuffix(FILE_HIGHLIGHT_NOTE)
            truncation_size -= len(FILE_HIGHLIGHT_NOTE)
            user_note = f"{FILE_HIGHLIGHT_NOTE}{user_note}"
        content = f"{content[:truncation_size]}…{user_note}"

    return content


async def codeblock_processor(message: dc.Message) -> ProcessedMessage:
    attachments = await _collect_attachments(message)
    zig_codeblocks = [c for c in extract_codeblocks(message.content) if c.lang == "zig"]

    if not zig_codeblocks:
        if not attachments:
            return ProcessedMessage(item_count=0)
        return ProcessedMessage(
            content=FILE_HIGHLIGHT_NOTE, files=attachments, item_count=len(attachments)
        )

    highlighted_codeblocks = [
        CodeBlock("ansi", apply_discord_wa(highlight_zig_code(c.body, THEME)))
        for c in zig_codeblocks
    ]
    max_length = 2000 - (len(FILE_HIGHLIGHT_NOTE) if attachments else 0)
    omitted_codeblocks = 0
    while len(code := "".join(map(str, highlighted_codeblocks))) > max_length:
        file = _tallest_codeblock_to_file(highlighted_codeblocks)

        if len(attachments) < 10:
            if not attachments:
                # We now have an attachment so the note is gonna be displayed
                max_length -= len(FILE_HIGHLIGHT_NOTE)
            attachments.append(file)
            continue

        if not omitted_codeblocks:
            # Expected final omission note size (conservative)
            max_length -= len(OMISSION_NOTE) + 5

        omitted_codeblocks += 1

    code = _add_user_notes(code, omitted_codeblocks, attachments)
    return ProcessedMessage(
        content=code,
        files=attachments,
        item_count=len(highlighted_codeblocks) + len(attachments),
    )


async def check_for_zig_code(message: dc.Message) -> None:
    if message.author.bot:
        return
    output = await codeblock_processor(message)
    if not output.item_count:
        return
    reply = await message.reply(
        output.content,
        view=CodeblockActions(message, output.item_count),
        files=output.files,
        mention_author=False,
    )
    codeblock_linker.link(message, reply)
    await remove_view_after_timeout(reply, 60)


zig_codeblock_delete_hook = create_delete_hook(linker=codeblock_linker)

zig_codeblock_edit_hook = create_edit_hook(
    linker=codeblock_linker,
    message_processor=codeblock_processor,
    interactor=check_for_zig_code,
    view_type=CodeblockActions,
    view_timeout=60,
)
