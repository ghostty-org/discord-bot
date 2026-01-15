import asyncio
import re
from typing import TYPE_CHECKING, final

import discord as dc
from discord.ext import commands

from app.common.linker import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    remove_view_after_delay,
)
from app.utils import suppress_embeds_after_delay

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.bot import GhosttyBot

type SiteTransformation = tuple[re.Pattern[str], Callable[[re.Match[str]], str | None]]


def _reddit_transformer(match: re.Match[str]) -> str | None:
    # Reddit supports `foo.reddit.com` as an alias for `reddit.com/r/foo`, but Rxddit
    # does not. However, Reddit also has a *bunch* of random subdomains. Rxddit handles
    # the skins (old.reddit.com and new.reddit.com) properly, so those are appended to
    # the URL. Apparently there's also a subdomain for every two-letter sequence, with
    # some being language codes and others being unused, which Rxddit doesn't handle, so
    # they're simply dropped by the regex below.

    # Post links have either a subdomain (representing the subreddit) or a subreddit, so
    # ignore everything else.
    if bool(match["subdomain"]) == bool(match["subreddit"]):
        return None

    skin = f"{s}." if (s := match["skin"]) else ""
    if subreddit := match["subreddit"]:
        # https://reddit.com/r///foo/comments/bar works apparently, but Rxddit doesn't
        # support it. Honestly don't blame them.
        subreddit = "r/" + subreddit.removeprefix("r").strip("/")
    else:
        # Append the subdomain as a subreddit if we don't already have one.
        subreddit = f"r/{match['subdomain']}"
    return f"https://{skin}rxddit.com/{subreddit}/{match['post']}"


VALID_URI_CHARS = r"[A-Za-z0-9-._~:/?#\[\]@!$&'()*+,;%=]"
EMBED_SITES: tuple[SiteTransformation, ...] = (
    (
        re.compile(
            r"https://(?:(?:www|(?P<skin>old|new)|\w\w|(?P<subdomain>[A-Za-z0-9_]+))\.)?reddit\.com/+"
            rf"(?P<subreddit>r/+[A-Za-z0-9_]+/+)?(?P<post>{VALID_URI_CHARS}+)"
        ),
        _reddit_transformer,
    ),
    (
        re.compile(
            r"https://(?:www\.)?(?P<site>x|twitter)\.com/"
            rf"(?P<post>{VALID_URI_CHARS}+/status/{VALID_URI_CHARS}+)"
        ),
        lambda match: (
            "https://"
            f"{'fixupx' if match['site'] == 'x' else 'fxtwitter'}.com/"
            f"{match['post']}"
        ),
    ),
    (
        re.compile(
            rf"https://(?:www\.)?pixiv\.net/({VALID_URI_CHARS}+/{VALID_URI_CHARS}+)"
        ),
        lambda match: f"https://phixiv.net/{match[1]}",
    ),
)
IGNORED_LINK = re.compile(rf"\<https://{VALID_URI_CHARS}+\>")


@final
class FixUpActions(ItemActions):
    action_singular = "linked this social media post"
    action_plural = "linked these social media posts"


@final
class FixupEmbeds(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.linker = MessageLinker()
        FixUpActions.linker = self.linker

    async def process(self, message: dc.Message) -> ProcessedMessage:
        matches: list[str | None] = []
        message_content = IGNORED_LINK.sub("", message.content)
        for pattern, transformer in EMBED_SITES:
            matches.extend(map(transformer, pattern.finditer(message_content)))

        links = list(filter(None, dict.fromkeys(matches)))
        omitted = False
        if len(links) > 5:
            omitted = True
            links = links[:5]
        while len(content := " ".join(links)) > 2000:
            links.pop()
            omitted = True

        return ProcessedMessage(
            content=content + "\n-# Some posts were omitted" * omitted,
            item_count=len(links),
        )

    @commands.Cog.listener()
    async def on_message_filter_passed(self, message: dc.Message) -> None:
        output = await self.process(message)
        if not output.item_count:
            return

        await message.edit(suppress=True)
        sent_message = await message.reply(
            output.content,
            mention_author=False,
            allowed_mentions=dc.AllowedMentions.none(),
            view=FixUpActions(message, output.item_count),
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
            interactor=self.on_message_filter_passed,
            view_type=FixUpActions,
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(FixupEmbeds(bot))
