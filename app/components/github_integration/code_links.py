from __future__ import annotations

import asyncio
import re
import string
import urllib.parse
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, NamedTuple, final, override

import discord as dc
from discord.ext import commands
from githubkit.exception import RequestFailed
from zig_codeblocks import highlight_zig_code

from app.common.cache import TTRCache
from app.common.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)
from app.components.zig_codeblocks import THEME
from app.utils import suppress_embeds_after_delay

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from githubkit import GitHub, TokenAuthStrategy

    from app.bot import GhosttyBot

CODE_LINK_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/([a-zA-Z0-9\-]+)/([a-zA-Z0-9\-\._]+)/blob/"
    r"([^/\s]+)/([^\?#\s]+)(?:[^\#\s]*)?#L(\d+)(?:C\d+)?(?:-L(\d+)(?:C\d+)?)?"
)
LANG_SUBSTITUTIONS = {
    "el": "lisp",
    "pyi": "py",
    "fnl": "clojure",
    "m": "objc",
}


class SnippetPath(NamedTuple):
    owner: str
    repo: str
    rev: str
    path: str


class Snippet(NamedTuple):
    repo: str
    path: str
    rev: str
    lang: str
    body: str
    range: slice


class ContentCache(TTRCache[SnippetPath, str]):
    def __init__(self, gh: GitHub[TokenAuthStrategy], **ttr: float) -> None:
        super().__init__(**ttr)
        self.gh: GitHub[TokenAuthStrategy] = gh

    @override
    async def fetch(self, key: SnippetPath) -> None:
        with suppress(RequestFailed):
            resp = await self.gh.rest.repos.async_get_content(
                key.owner,
                key.repo,
                key.path,
                ref=key.rev,
                headers={"Accept": "application/vnd.github.raw+json"},
            )
            self[key] = resp.text


@final
class CodeLinkActions(ItemActions):
    action_singular = "linked this code snippet"
    action_plural = "linked these code snippets"


@final
class CodeLinks(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.linker = MessageLinker()
        CodeLinkActions.linker = self.linker
        self.cache = ContentCache(self.bot.gh, minutes=30)

    async def get_snippets(self, content: str) -> AsyncGenerator[Snippet]:
        for match in CODE_LINK_PATTERN.finditer(content):
            *snippet_path, range_start, range_end = match.groups()
            snippet_path[-1] = snippet_path[-1].rstrip("/")

            snippet_path = SnippetPath(*snippet_path)
            range_start = int(range_start)
            # slice(a - 1, b) since lines are 1-indexed
            content_range = slice(
                range_start - 1,
                int(range_end) if range_end else range_start,
            )

            if not (snippet := await self.cache.get(snippet_path)):
                continue
            selected_lines = "\n".join(snippet.splitlines()[content_range])
            lang = snippet_path.path.rpartition(".")[2]
            if lang == "zig":
                lang = "ansi"
                selected_lines = highlight_zig_code(selected_lines, THEME)
            lang = LANG_SUBSTITUTIONS.get(lang, lang)
            yield Snippet(
                f"{snippet_path.owner}/{snippet_path.repo}",
                snippet_path.path,
                snippet_path.rev,
                lang,
                dedent(selected_lines),
                content_range,
            )

    @staticmethod
    def _format_snippet(snippet: Snippet, *, include_body: bool = True) -> str:
        repo_url = f"https://github.com/{snippet.repo}"
        tree_url = f"{repo_url}/tree/{snippet.rev}"
        file_url = f"{repo_url}/blob/{snippet.rev}/{snippet.path}"
        line_num = snippet.range.start + 1
        range_info = (
            f"[lines {line_num}–{snippet.range.stop}]"  # noqa: RUF001
            f"(<{file_url}#L{line_num}-L{snippet.range.stop}>)"  # Not an en dash.
            if snippet.range.stop > line_num
            else f"[line {line_num}](<{file_url}#L{line_num}>)"
        )
        unquoted_path = urllib.parse.unquote(snippet.path)
        ref_type = (
            "revision" if all(c in string.hexdigits for c in snippet.rev) else "branch"
        )
        return (
            f"[`{unquoted_path}`](<{file_url}>), {range_info}"
            f"\n-# Repo: [`{snippet.repo}`](<{repo_url}>),"
            f" {ref_type}: [`{snippet.rev}`](<{tree_url}>)"
        ) + (f"\n```{snippet.lang}\n{snippet.body}\n```" * include_body)

    async def process(self, message: dc.Message) -> ProcessedMessage:
        snippets = [s async for s in self.get_snippets(message.content)]
        if not snippets:
            return ProcessedMessage(item_count=0)

        blobs = list(map(self._format_snippet, snippets))

        if len(blobs) == 1 and len(blobs[0]) > 2000:
            # When there is only a single blob which goes over the limit, upload it as
            # a file instead.
            snippet = snippets[0]
            # Correct the filename to use the snippet's language in case it
            # differs from the filename's extension, which is done for multiple
            # file types by get_snippets().
            filename = Path(snippet.path).with_suffix(f".{snippet.lang}").name
            return ProcessedMessage(
                content=self._format_snippet(snippet, include_body=False),
                files=[dc.File(BytesIO(snippet.body.encode()), filename=filename)],
                item_count=1,
            )

        if len("\n\n".join(blobs)) > 2000:
            while len("\n\n".join(blobs)) > 1970:  # Accounting for omission note
                blobs.pop()
            if not blobs:
                # Signal that all snippets were omitted
                return ProcessedMessage(item_count=-1)
            blobs.append("-# Some snippets were omitted")
        return ProcessedMessage(content="\n".join(blobs), item_count=len(snippets))

    @commands.Cog.listener("on_message_filter_passed")
    async def reply_with_code(self, message: dc.Message) -> None:
        output = await self.process(message)
        if output.item_count != 0:
            await message.edit(suppress=True)
        if output.item_count < 1:
            return

        sent_message = await message.reply(
            output.content,
            files=output.files,
            suppress_embeds=True,
            mention_author=False,
            allowed_mentions=dc.AllowedMentions.none(),
            view=CodeLinkActions(message, output.item_count),
        )
        self.linker.link(message, sent_message)
        async with asyncio.TaskGroup() as group:
            group.create_task(suppress_embeds_after_delay(message))
            group.create_task(remove_view_after_delay(sent_message))

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=self.process,
            interactor=self.reply_with_code,
            view_type=CodeLinkActions,
            view_timeout=60,
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(CodeLinks(bot))
