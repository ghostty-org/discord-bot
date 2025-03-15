import re
import urllib.parse
from collections.abc import AsyncIterator
from typing import NamedTuple

import discord
from zig_codeblocks import highlight_zig_code

from .cache import TTRCache
from app.components.zig_codeblocks import THEME
from app.setup import gh
from app.utils import (
    DeleteMessage,
    MessageLinker,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)

CODE_LINK_PATTERN = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/([^\?#]+)(?:[^\#]*)?#L(\d+)(?:-L(\d+))?"
)


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
    async def fetch(self, key: SnippetPath) -> None:
        resp = await gh.rest.repos.async_get_content(
            key.owner,
            key.repo,
            key.path,
            ref=key.rev,
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        self[key] = resp.text


content_cache = ContentCache(1800)  # 30 minutes
code_linker = MessageLinker()


class DeleteCodeLink(DeleteMessage):
    linker = code_linker
    action_singular = "linked this code snippet"
    action_plural = "linked these code snippets"


async def get_snippets(content: str) -> AsyncIterator[Snippet]:
    for match in CODE_LINK_PATTERN.finditer(content):
        *snippet_path, range_start, range_end = match.groups()

        snippet_path = SnippetPath(*snippet_path)
        range_start = int(range_start)
        # slice(a - 1, b) since lines are 1-indexed
        content_range = slice(
            range_start - 1,
            int(range_end) if range_end else range_start,
        )

        snippet = await content_cache.get(snippet_path)
        selected_lines = "\n".join(snippet.splitlines()[content_range])
        lang = snippet_path.path.rpartition(".")[2]
        if lang == "zig":
            lang = "ansi"
            selected_lines = highlight_zig_code(selected_lines, THEME)
        yield Snippet(
            f"{snippet_path.owner}/{snippet_path.repo}",
            snippet_path.path,
            snippet_path.rev,
            lang,
            selected_lines,
            content_range,
        )


def _format_snippet(snippet: Snippet) -> str:
    range_info = (
        f"lines {snippet.range.start + 1}–{snippet.range.stop}"  # noqa: RUF001
        if snippet.range.stop > snippet.range.start + 1
        else f"line {snippet.range.start + 1}"
    )
    unquoted_path = urllib.parse.unquote(snippet.path)
    return (
        f"`{unquoted_path}`, {range_info}"
        f"\n-# Repo: `{snippet.repo}`, revision: `{snippet.rev}`"
        f"\n```{snippet.lang}\n{snippet.body}\n```"
    )


async def snippet_message(message: discord.Message) -> tuple[str, int]:
    snippets = [s async for s in get_snippets(message.content)]
    if not snippets:
        return "", 0

    blobs = list(map(_format_snippet, snippets))

    if len("\n\n".join(blobs)) > 2000:
        while len("\n\n".join(blobs)) > 1970:  # Accounting for omission note
            blobs.pop()
        if not blobs:
            return "", -1  # Signal that all snippets were omitted
        blobs.append("-# Some snippets were omitted")
    return "\n".join(blobs), len(snippets)


async def reply_with_code(message: discord.Message) -> None:
    if message.author.bot:
        return
    msg_content, snippet_count = await snippet_message(message)
    if snippet_count != 0:
        await message.edit(suppress=True)
    if snippet_count < 1:
        return

    sent_message = await message.reply(
        msg_content,
        suppress_embeds=True,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
        view=DeleteCodeLink(message, snippet_count),
    )
    code_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


code_link_delete_hook = create_delete_hook(linker=code_linker)

code_link_edit_hook = create_edit_hook(
    linker=code_linker,
    message_processor=snippet_message,
    interactor=reply_with_code,
    view_type=DeleteCodeLink,
)
