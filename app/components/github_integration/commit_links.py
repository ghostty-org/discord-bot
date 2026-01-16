import asyncio
import copy
import re
import string
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, final

import discord as dc
from discord.ext import commands

from app.components.github_integration.commit_types import CommitCache, CommitKey
from app.components.github_integration.entities.resolution import resolve_repo_signature
from toolbox.discord import (
    dynamic_timestamp,
    suppress_embeds_after_delay,
)
from toolbox.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)
from toolbox.misc import format_diff_note

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterable

    from app.bot import GhosttyBot
    from app.components.github_integration.commit_types import CommitSummary

COMMIT_SHA_PATTERN = re.compile(
    r"(?P<site>\bhttps?://(?:www\.)?github\.com/)?"
    r"\b(?:"
        r"(?P<owner>\b[a-z0-9\-]+/)?"
        r"(?P<repo>\b[a-z0-9\-\._]+)"
        r"(?P<sep>@|/commit/|/blob/)"
    r")?"
    # Ignore SHAs preceded by sequences like <@ or <#, as those are probably snowflakes.
    r"(?<!<[^a-f0-9\s])(?P<sha>[a-f0-9]{7,40})\b",
    re.IGNORECASE,
)  # fmt: skip


@final
class CommitActions(ItemActions):
    action_singular = "mentioned this commit"
    action_plural = "mentioned these commits"


@final
class CommitLinks(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
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

    async def resolve_repo_signatures(
        self, sigs: Iterable[tuple[str, str, str, str, str]]
    ) -> AsyncGenerator[CommitKey]:
        valid_signatures = 0
        for site, owner, repo, sep, sha in sigs:
            if sep == "/blob/":
                continue  # This is likely a code link
            if bool(site) != (sep == "/commit/"):
                continue  # Separator was `@` despite this being a link or vice versa
            if site and not owner:
                continue  # Not a valid GitHub link
            if sig := await resolve_repo_signature(
                self.bot.config, owner or None, repo or None
            ):
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

    @commands.Cog.listener("on_message_filter_passed")
    async def reply_with_commit_details(self, message: dc.Message) -> None:
        output = await self.process(message)
        if not output.item_count:
            return
        await message.edit(suppress=True)
        reply = await message.reply(
            output.content,
            mention_author=False,
            suppress_embeds=True,
            allowed_mentions=dc.AllowedMentions.none(),
            view=CommitActions(message, output.item_count),
        )
        self.linker.link(message, reply)
        async with asyncio.TaskGroup() as group:
            group.create_task(suppress_embeds_after_delay(message))
            group.create_task(remove_view_after_delay(reply))

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


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(CommitLinks(bot))
