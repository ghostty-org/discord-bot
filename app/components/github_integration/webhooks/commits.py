from __future__ import annotations

import asyncio
import copy
import re
import string
from types import SimpleNamespace
from typing import TYPE_CHECKING, NamedTuple, cast, final, override

import discord as dc
from discord.ext import commands
from githubkit.exception import RequestFailed
from loguru import logger

from app.common.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)
from app.components.github_integration.entities.resolution import resolve_repo_signature
from app.components.github_integration.models import GitHubUser
from app.components.github_integration.webhooks.core import (
    EmbedContent,
    Footer,
    send_embed,
)
from app.utils import dynamic_timestamp, format_diff_note, suppress_embeds_after_delay

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import AsyncGenerator, Iterable

    from githubkit import GitHub, TokenAuthStrategy
    from monalisten import Monalisten, events

    from app.bot import GhosttyBot

COMMIT_SHA_PATTERN = re.compile(
    r"(?P<site>\bhttps?://(?:www\.)?github\.com/)?"
    r"\b(?:"
        r"(?P<owner>\b[a-z0-9\-]+/)?"
        r"(?P<repo>\b[a-z0-9\-\._]+)"
        r"(?P<sep>@|/commit/|/blob/)"
    r")?"
    r"(?P<sha>[a-f0-9]{7,40})\b",
    re.IGNORECASE,
)  # fmt: skip


class CommitKey(NamedTuple):
    owner: str
    repo: str
    sha: str


class CommitSummary(NamedTuple):
    sha: str
    author: GitHubUser | None
    committer: GitHubUser | None
    message: str
    additions: int
    deletions: int
    files_changed: int
    url: str
    date: dt.datetime | None
    signed: bool


@final
class CommitCache:
    def __init__(self, gh: GitHub[TokenAuthStrategy]) -> None:
        self.gh = gh
        self._cache: dict[CommitKey, CommitSummary] = {}

    def _filter_prefix(self, prefix: str) -> list[CommitKey]:
        return [key for key in self._cache if key.sha.startswith(prefix)]

    async def get(self, key: CommitKey) -> CommitSummary | None:
        match self._filter_prefix(key.sha):
            case []:
                return await self._fetch(key)
            case [full_sha]:
                return self._cache.get(full_sha)
            case _:
                # Behave like GitHub: treat ambiguous short SHAs as invalid
                return None

    async def _fetch(self, key: CommitKey) -> CommitSummary | None:
        try:
            resp = await self.gh.rest.repos.async_get_commit(*key)
        except RequestFailed:
            return None
        obj = resp.parsed_data
        stats = obj.stats or 0
        commit_summary = CommitSummary(
            sha=obj.sha,
            author=GitHubUser(**a.model_dump()) if (a := obj.author) else None,
            committer=GitHubUser(**c.model_dump()) if (c := obj.committer) else None,
            message=obj.commit.message,
            additions=stats and (stats.additions or 0),
            deletions=stats and (stats.deletions or 0),
            files_changed=len(obj.files or ()),
            url=obj.html_url,
            date=(c := obj.commit.committer) and (c.date or None),
            signed=bool((v := obj.commit.verification) and v.verified),
        )
        key_with_full_sha = copy.replace(key, sha=obj.sha)
        self._cache[key_with_full_sha] = commit_summary
        return commit_summary


@final
class CommitActions(ItemActions):
    action_singular = "mentioned this commit"
    action_plural = "mentioned these commits"


@final
class Commits(commands.Cog):
    def __init__(self, bot: GhosttyBot, monalisten_client: Monalisten) -> None:
        self.bot = bot
        self.monalisten_client = monalisten_client
        self.linker = MessageLinker()
        CommitActions.linker = MessageLinker()
        self.cache = CommitCache(self.bot.gh)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Pass a commit mention of the current commit back to the bot's status
        # functionality for display.
        if commit_url := self.bot.bot_status.commit_url:
            # Avoid race condition with bot.py on_ready, by forcing emojis to be loaded.
            await self.bot.load_emojis()
            fake_message = cast("dc.Message", SimpleNamespace(content=commit_url))
            if (links := await self.process(fake_message)).item_count:
                self.bot.bot_status.commit_data = links.content

    @override
    async def cog_load(self) -> None:
        @self.monalisten_client.event.commit_comment
        async def _(event: events.CommitComment) -> None:
            full_sha = event.comment.commit_id
            sha = full_sha[:7]

            owner, _, repo_name = event.repository.full_name.partition("/")
            if commit_summary := await self.cache.get(
                CommitKey(owner, repo_name, full_sha)
            ):
                commit_title = commit_summary.message.splitlines()[0]
            else:
                logger.warning("no commit summary found for {}", full_sha)
                commit_title = "(no commit message found)"

            await send_embed(
                self.bot,
                event.sender,
                EmbedContent(
                    f"commented on commit `{sha}`",
                    event.comment.html_url,
                    event.comment.body,
                ),
                Footer("commit", f"Commit {sha}: {commit_title}"),
            )

    def _format(self, commit: CommitSummary) -> str:
        emoji = self.bot.ghostty_emojis["commit"]
        title = commit.message.splitlines()[0]
        heading = f"{emoji} **Commit [`{commit.sha[:7]}`](<{commit.url}>):** {title}"

        if commit.committer and commit.committer.name == "web-flow":
            # `web-flow` is GitHub's committer account for all web commits (like merge
            # or revert) made on GitHub.com, so let's pretend the commit author is
            # actually the committer.
            commit = copy.replace(commit, committer=commit.author)

        subtext = "\n-# authored by "
        if (a := commit.author) and (c := commit.committer) and a.name != c.name:
            subtext += f"{commit.author.hyperlink}, committed by "

        if commit.signed:
            subtext += "🔏 "

        subtext += commit.committer.hyperlink if commit.committer else "an unknown user"

        repo_url = commit.url.rstrip(string.hexdigits).removesuffix("/commit/")
        _, owner, name = repo_url.rsplit("/", 2)
        subtext += f" in [`{owner}/{name}`](<{repo_url}>)"

        if commit.date:
            subtext += f" on {dynamic_timestamp(commit.date, 'D')}"
            subtext += f" ({dynamic_timestamp(commit.date, 'R')})"

        diff_note = format_diff_note(
            commit.additions, commit.deletions, commit.files_changed
        )
        if diff_note is not None:
            subtext += f"\n-# {diff_note}"

        return heading + subtext

    @staticmethod
    async def resolve_repo_signatures(
        sigs: Iterable[tuple[str, str, str, str, str]],
    ) -> AsyncGenerator[CommitKey]:
        valid_signatures = 0
        for site, owner, repo, sep, sha in sigs:
            if sep == "/blob/":
                continue  # This is likely a code link
            if bool(site) != (sep == "/commit/"):
                continue  # Separator was `@` despite this being a link or vice versa
            if site and not owner:
                continue  # Not a valid GitHub link
            if sig := await resolve_repo_signature(owner or None, repo or None):
                yield CommitKey(*sig, sha)
                valid_signatures += 1
                if valid_signatures == 10:
                    break

    async def process(self, message: dc.Message) -> ProcessedMessage:
        shas = dict.fromkeys(COMMIT_SHA_PATTERN.findall(message.content))
        shas = [r async for r in self.resolve_repo_signatures(shas)]
        commit_summaries = await asyncio.gather(*(self.cache.get(c) for c in shas))
        valid_shas = list(filter(None, commit_summaries))
        content = "\n\n".join(map(self._format, valid_shas))
        return ProcessedMessage(item_count=len(valid_shas), content=content)

    @commands.Cog.listener("on_message")
    async def reply_with_commit_details(self, message: dc.Message) -> None:
        if message.author.bot or self.bot.fails_message_filters(message):
            return
        output = await self.process(message)
        if output.item_count == 0:
            return
        reply = await message.reply(
            output.content,
            mention_author=False,
            suppress_embeds=True,
            allowed_mentions=dc.AllowedMentions.none(),
            view=CommitActions(message, output.item_count),
        )
        self.linker.link(message, reply)
        await asyncio.gather(
            suppress_embeds_after_delay(message),
            remove_view_after_delay(reply),
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: dc.Message) -> None:
        await self.linker.delete(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: dc.Message, after: dc.Message) -> None:
        await self.linker.edit(
            before,
            after,
            message_processor=self.process,
            interactor=self.reply_with_commit_details,
            view_type=CommitActions,
            view_timeout=60,
        )
