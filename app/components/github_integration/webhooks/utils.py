import copy
import datetime as dt
import difflib
import re
from functools import partial
from itertools import islice
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol, TypedDict

import discord as dc
from monalisten import events

from app.bot import emojis
from app.components.github_integration.models import GitHubUser
from app.config import config
from toolbox.misc import COLOR_PALETTE, truncate

if TYPE_CHECKING:
    from githubkit.versions.latest.models import RepositoryWebhooks, SimpleUser

    from app.bot import EmojiName
    from app.config import WebhookFeedType
    from toolbox.misc import EmbedColor

CODEBLOCK = re.compile(r"`{3,}")
SUBTEXT_HTML = re.compile(r"\s*<(su[pb])>(.+?)</\1>\s*?\n?")
GITHUB_DISCUSSION_URL = re.compile(
    # Ignore if already inside a hyperlink
    r"(?<!\()"
        r"https://github\.com/"
        r"(?P<owner>\b[a-zA-Z0-9\-]+)/"
        r"(?P<repo>\b[a-zA-Z0-9\-\._]+)"
        r"(?P<sep>/(?:issues|pull|discussions)/)"
        r"(?P<number>\d+)"
    r"(?!\))"
)  # fmt: skip


class EmbedContentArgs(TypedDict, total=False):
    title: str
    url: str
    description: str | None


class EmbedContent(NamedTuple):
    title: str
    url: str
    body: str | None = None
    description: str | None = None

    @property
    def dict(self) -> EmbedContentArgs:
        args: EmbedContentArgs = {"title": self.title, "url": self.url}
        if self.description:
            # If a description is provided explicitly, don't truncate. However, Discord
            # has a description character size limit.
            args["description"] = truncate(self.description, 4096)
        elif self.body:
            args["description"] = truncate(self.body, 500)
        return args


class Footer(NamedTuple):
    icon: EmojiName
    text: str

    @property
    def dict(self) -> dict[str, str | None]:
        return {
            "text": self.text,
            "icon_url": getattr(emojis()[self.icon], "url", None),
        }


class ContentGenerator(Protocol):
    def __call__(
        self,
        event_like: Any,
        template: str,
        body: str | None = None,
        /,
        *,
        description: str | None = None,
    ) -> EmbedContent: ...


class FooterGenerator(Protocol):
    def __call__(self, event_like: Any, /, *args: Any, **kwargs: Any) -> Footer: ...


def _convert_codeblock(match: re.Match[str]) -> str:
    return "\u2035" * len(match[0])


async def send_edit_difference(
    event: events.IssuesEdited | events.PullRequestEdited,
    content_generator: ContentGenerator,
    footer_generator: FooterGenerator,
) -> None:
    event_object = (
        event.issue if isinstance(event, events.IssuesEdited) else event.pull_request
    )

    if event_object.created_at > dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=15):
        return

    changes = event.changes
    if changes.body and changes.body.from_:
        # HACK: replace all 3+ backticks with reverse primes to avoid breaking the diff
        # block while maintaining the intent.
        from_file = CODEBLOCK.sub(_convert_codeblock, changes.body.from_).splitlines()
        to_file = (
            CODEBLOCK.sub(_convert_codeblock, event_object.body).splitlines()
            if event_object.body
            else []
        )
        old_title = changes.title.from_ if changes.title else event_object.title
        new_title = event_object.title
        diff_lines = difflib.unified_diff(
            from_file, to_file, fromfile=old_title, tofile=new_title, lineterm=""
        )
        if old_title == new_title:
            # If the titles are the same, there's no point in showing them;
            # they just take up a lot of the 750 available characters.
            diff_lines = islice(diff_lines, 2, None)
        diff = truncate("\n".join(diff_lines), 750 - len("```diff\n\n```"))
        verb = "edited"
        content = f"```diff\n{diff}\n```"
    elif changes.title:
        # GitHub's title limit is 256 characters, so this will never exceed 526
        # characters.
        verb = "renamed"
        content = f"```diff\n-{changes.title.from_}\n+{event_object.title}```"
    else:
        return

    assert event.sender
    await send_embed(
        event.sender,
        content_generator(event_object, f"{verb} {{}}", None, description=content),
        footer_generator(event_object),
    )


def _shorten_same_repo_links(
    origin_repo: RepositoryWebhooks, matchobj: re.Match[str]
) -> str:
    owner, _, repo = origin_repo.full_name.partition("/")
    if matchobj["owner"] == owner and matchobj["repo"] == repo:
        # Only short hand if link comes from same repo
        return f"[#{matchobj['number']}]({matchobj[0]})"
    return matchobj[0]


async def send_embed(  # noqa: PLR0913
    actor: SimpleUser,
    content: EmbedContent,
    footer: Footer,
    *,
    color: EmbedColor | None = None,
    feed_type: WebhookFeedType = "main",
    origin_repo: RepositoryWebhooks | None = None,
) -> None:
    if origin_repo and content.body:
        body = SUBTEXT_HTML.sub(r"\n-# \g<2>\n", content.body)
        body = GITHUB_DISCUSSION_URL.sub(
            partial(_shorten_same_repo_links, origin_repo), body
        )
        content = copy.replace(content, body=body)

    author = GitHubUser(**actor.model_dump())
    embed = (
        dc
        .Embed(color=color and COLOR_PALETTE.get(color), **content.dict)
        .set_footer(**footer.dict)
        .set_author(**author.model_dump())
    )
    await config().webhook_channels[feed_type].send(embed=embed)
