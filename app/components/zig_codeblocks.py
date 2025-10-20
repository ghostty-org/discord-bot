from __future__ import annotations

import re
import string
from functools import partial
from io import BytesIO
from random import choices
from typing import TYPE_CHECKING, Self, final

import discord as dc
from discord.ext import commands
from zig_codeblocks import (
    DEFAULT_THEME,
    CodeBlock,
    extract_codeblocks,
    highlight_zig_code,
    process_markdown,
)

from app.common.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)
from app.common.message_moving import get_or_create_webhook, move_message

if TYPE_CHECKING:
    from collections.abc import Collection

    from app.bot import GhosttyBot

MAX_CONTENT = 51_200  # 50 KiB
MAX_ZIG_FILE_SIZE = 8_388_608  # 8 MiB
FILE_HIGHLIGHT_NOTE = '\nOn desktop, click "View whole file" to see the highlighting.'
OMISSION_NOTE = "\n-# {} codeblock{} omitted"

# This pattern is intentionally simple; it's only meant to operate on sequences produced
# by zig-codeblocks which will never appear in any other form.
SGR_PATTERN = re.compile(r"\x1b\[[0-9;]+m")
THEME = DEFAULT_THEME.copy()
del THEME["Comment"]


def _apply_discord_wa(source: str) -> str:
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


def _apply_discord_wa_in_ansi_codeblocks(source: str) -> str:
    # Resolves #274
    for block in set(extract_codeblocks(source)):
        if block.lang == "ansi":
            body = str(block)
            source = source.replace(body, _apply_discord_wa(body))
    return source


@final
class CodeblockActions(ItemActions):
    action_singular = "sent this code block"
    action_plural = "sent these code blocks"

    def __init__(self, bot: GhosttyBot, message: dc.Message, item_count: int) -> None:
        super().__init__(message, item_count)
        self.bot = bot
        replaced_content = _apply_discord_wa_in_ansi_codeblocks(
            process_markdown(message.content, THEME)
        )
        if len(replaced_content) > 2000:
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
        await move_message(
            self.bot, webhook, self.message, thread=thread, include_move_marks=False
        )


@final
class ZigCodeblocks(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.linker = MessageLinker()
        CodeblockActions.linker = self.linker

    @staticmethod
    async def _collect_attachments(message: dc.Message) -> list[dc.File]:
        attachments: list[dc.File] = []
        for att in message.attachments:
            if not att.filename.endswith(".zig") or att.size > MAX_ZIG_FILE_SIZE:
                continue
            content = (await att.read())[:MAX_CONTENT]
            if content.count(b"\n") <= 5 and len(content) <= 1900:
                message.content = (
                    f"{CodeBlock('zig', content.decode())}\n{message.content}"
                )
                continue
            attachments.append(
                dc.File(
                    BytesIO(highlight_zig_code(content, THEME).encode()),
                    att.filename + ".ansi",
                )
            )
        return attachments

    @staticmethod
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

    @staticmethod
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

    async def process(self, message: dc.Message) -> ProcessedMessage:
        attachments = await self._collect_attachments(message)
        zig_codeblocks = [
            c for c in extract_codeblocks(message.content) if c.lang == "zig"
        ]

        if not zig_codeblocks:
            if not attachments:
                return ProcessedMessage(item_count=0)
            return ProcessedMessage(
                content=FILE_HIGHLIGHT_NOTE,
                files=attachments,
                item_count=len(attachments),
            )

        highlighted_codeblocks = [
            CodeBlock("ansi", _apply_discord_wa(highlight_zig_code(c.body, THEME)))
            for c in zig_codeblocks
        ]
        max_length = 2000 - (len(FILE_HIGHLIGHT_NOTE) if attachments else 0)
        omitted_codeblocks = 0
        while len(code := "".join(map(str, highlighted_codeblocks))) > max_length:
            file = self._tallest_codeblock_to_file(highlighted_codeblocks)

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

        return ProcessedMessage(
            content=self._add_user_notes(code, omitted_codeblocks, attachments),
            files=attachments,
            item_count=len(highlighted_codeblocks) + len(attachments),
        )

    @commands.Cog.listener("on_message_filter_passed")
    async def check_for_zig_code(self, message: dc.Message) -> None:
        output = await self.process(message)
        if not output.item_count:
            return
        reply = await message.reply(
            output.content,
            view=CodeblockActions(self.bot, message, output.item_count),
            files=output.files,
            mention_author=False,
        )
        self.linker.link(message, reply)
        await remove_view_after_delay(reply, 60)

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=self.process,
            interactor=self.check_for_zig_code,
            view_type=partial(CodeblockActions, self.bot),
            view_timeout=60,
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(ZigCodeblocks(bot))
