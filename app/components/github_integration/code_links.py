import re
import string
import urllib.parse
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from textwrap import dedent
from typing import NamedTuple

import discord as dc
from zig_codeblocks import highlight_zig_code

from app.common.cache import TTRCache
from app.common.hooks import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    create_delete_hook,
    create_edit_hook,
    remove_view_after_timeout,
)
from app.components.zig_codeblocks import THEME
from app.setup import gh

CODE_LINK_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s]+)/blob/([^/\s]+)/([^\?#\s]+)"
    r"(?:[^\#\s]*)?#L(\d+)(?:C\d+)?(?:-L(\d+)(?:C\d+)?)?"
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
    async def fetch(self, key: SnippetPath) -> None:
        resp = await gh.rest.repos.async_get_content(
            key.owner,
            key.repo,
            key.path,
            ref=key.rev,
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        self[key] = resp.text


content_cache = ContentCache(minutes=30)
code_linker = MessageLinker()


class CodeLinkActions(ItemActions):
    linker = code_linker
    action_singular = "linked this code snippet"
    action_plural = "linked these code snippets"


async def get_snippets(content: str) -> AsyncIterator[Snippet]:
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

        snippet = await content_cache.get(snippet_path)
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


async def snippet_message(message: dc.Message) -> ProcessedMessage:
    snippets = [s async for s in get_snippets(message.content)]
    if not snippets:
        return ProcessedMessage(item_count=0)

    blobs = list(map(_format_snippet, snippets))

    if len(blobs) == 1 and len(blobs[0]) > 2000:
        # When there is only a single blob which goes over the limit, upload it as
        # a file instead.
        fp = BytesIO(snippets[0].body.encode())
        file = dc.File(fp, filename=Path(snippets[0].path).name)
        return ProcessedMessage(
            content=_format_snippet(snippets[0], include_body=False),
            files=[file],
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


async def reply_with_code(message: dc.Message) -> None:
    if message.author.bot:
        return
    output = await snippet_message(message)
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
    code_linker.link(message, sent_message)
    await remove_view_after_timeout(sent_message)


code_link_delete_hook = create_delete_hook(linker=code_linker)

code_link_edit_hook = create_edit_hook(
    linker=code_linker,
    message_processor=snippet_message,
    interactor=reply_with_code,
    view_type=CodeLinkActions,
)
