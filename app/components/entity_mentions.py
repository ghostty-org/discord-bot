import asyncio
import datetime as dt
import re
from contextlib import suppress
from types import SimpleNamespace
from typing import Literal, Protocol, cast

import discord
import github
from discord import Message
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository

from app.setup import bot, config, gh
from app.utils import is_dm, is_mod, try_dm

GITHUB_URL = "https://github.com"
ENTITY_REGEX = re.compile(r"(?:\b(web|bot|main))?#(\d{1,6})(?!\.\d)\b")
ENTITY_TEMPLATE = "**{kind} [#{entity.number}](<{entity.html_url}>):** {entity.title}"
IGNORED_MESSAGE_TYPES = frozenset(
    (discord.MessageType.thread_created, discord.MessageType.channel_name_change)
)
REPOSITORIES: dict[str, Repository] = {
    kind: gh.get_repo(f"{config.GITHUB_ORG}/{name}", lazy=True)
    for kind, name in config.GITHUB_REPOS.items()
}
EMOJI_NAMES = frozenset(
    {
        "discussion_answered",
        "issue_closed_completed",
        "issue_closed_unplanned",
        "issue_draft",
        "issue_open",
        "pull_closed",
        "pull_draft",
        "pull_merged",
        "pull_open",
    }
)

DISCUSSION_QUERY = """
query getDiscussion($number: Int!, $org: String!, $repo: String!) {
  repository(owner: $org, name: $repo) {
    discussion(number: $number) {
      title
      number
      user: author { login }
      created_at: createdAt
      html_url: url
      answered: isAnswered
    }
  }
}
"""

type RepoName = Literal["web", "bot", "main"]
type CacheKey = tuple[RepoName, int]
type EntityKind = Literal["Pull Request", "Issue", "Discussion"]


class DeleteMention(discord.ui.View):
    def __init__(self, message: discord.Message, entity_count: int) -> None:
        super().__init__()
        self.message = message
        self.plural = entity_count > 1

    @discord.ui.button(
        label="Delete",
        emoji="🗑️",
        style=discord.ButtonStyle.gray,
    )
    async def delete(
        self, interaction: discord.Interaction, but: discord.ui.Button
    ) -> None:
        if interaction.user.id == self.message.author.id or is_mod(interaction.user):
            assert interaction.message
            await interaction.message.delete()
            _unlink_original_message(interaction.message)
            return

        await interaction.response.send_message(
            "Only the person who mentioned "
            + ("these entities" if self.plural else "this entity")
            + " can remove this message.",
            ephemeral=True,
        )


class GitHubUser(Protocol):
    login: str


class Entity(Protocol):
    number: int
    title: str
    html_url: str
    user: GitHubUser
    created_at: dt.datetime


class TTRCache:
    def __init__(self, ttr: int) -> None:
        self._ttr = dt.timedelta(seconds=ttr)
        self._cache: dict[CacheKey, tuple[dt.datetime, EntityKind, Entity]] = {}

    def _fetch_entity(self, key: CacheKey) -> None:
        repo_name, entity_id = key
        repo = REPOSITORIES[repo_name]
        try:
            entity = repo.get_issue(entity_id)
            kind = "Issue"
            if entity.pull_request:
                entity = repo.get_pull(entity_id)
                kind = "Pull Request"
        except github.UnknownObjectException:
            entity = get_discussion(repo, entity_id)
            kind = "Discussion"
        self._cache[key] = (dt.datetime.now(), kind, cast(Entity, entity))

    def _refresh(self, key: CacheKey) -> None:
        if key not in self._cache:
            self._fetch_entity(key)
            return
        timestamp, *_ = self._cache[key]
        if dt.datetime.now() - timestamp >= self._ttr:
            self._fetch_entity(key)

    def __getitem__(self, key: CacheKey) -> tuple[EntityKind, Entity]:
        self._refresh(key)
        _, kind, entity = self._cache[key]
        return kind, entity


entity_cache = TTRCache(1800)  # 30 minutes

message_to_mentions: dict[discord.Message, discord.Message] = {}

entity_emojis: dict[str, discord.Emoji] = {}


def _unlink_original_message(message: discord.Message) -> None:
    original_message = next(
        (msg for msg, reply in message_to_mentions.items() if reply == message),
        None,
    )
    if original_message is not None:
        del message_to_mentions[original_message]


async def load_emojis() -> None:
    guild = next(g for g in bot.guilds if "ghostty" in g.name.casefold())
    for emoji in guild.emojis:
        if emoji.name in EMOJI_NAMES:
            entity_emojis[emoji.name] = emoji
    if len(entity_emojis) < len(EMOJI_NAMES):
        log_channel = cast(discord.TextChannel, bot.get_channel(config.LOG_CHANNEL_ID))
        await log_channel.send(
            "Failed to load the following emojis: "
            + ", ".join(EMOJI_NAMES - entity_emojis.keys())
        )


def _format_mention(entity: Entity, kind: EntityKind) -> str:
    headline = ENTITY_TEMPLATE.format(kind=kind, entity=entity)

    # Include author and creation date
    author = entity.user.login
    subtext = (
        f"-# by [`{author}`](<{GITHUB_URL}/{author}>)"
        f" on {entity.created_at:%b %d, %Y}\n"
    )

    if isinstance(entity, Issue):
        state = "open" if entity.state == "open" else "closed_"
        if entity.state == "closed":
            state += "completed" if entity.state_reason == "completed" else "unplanned"
        emoji = entity_emojis.get(f"issue_{state}")
    elif isinstance(entity, PullRequest):
        state = "draft" if entity.draft else "merged" if entity.merged else entity.state
        emoji = entity_emojis.get(f"pull_{state}")
    else:
        # Discussion
        answered = getattr(entity, "answered", False)
        emoji = entity_emojis.get("discussion_answered" if answered else "issue_draft")

    return f"{emoji or ":question:"} {headline}\n{subtext}"


def _get_entities(message: discord.Message) -> tuple[str, int]:
    matches = dict.fromkeys(m.groups() for m in ENTITY_REGEX.finditer(message.content))
    omitted = 0
    if len(matches) > 10:
        # Too many mentions, preventing a DoS
        omitted = len(matches) - 10
        matches = list(matches)[:10]

    entities: list[str] = []
    for repo_name, number_ in matches:
        number = int(number_)
        try:
            kind, entity = entity_cache[cast(RepoName, repo_name or "main"), number]
        except KeyError:
            continue
        if entity.number < 10 and repo_name is None:
            # Ignore single-digit mentions (likely a false positive)
            continue
        entities.append(_format_mention(entity, kind))

    if len("\n".join(entities)) > 2000:
        while len("\n".join(entities)) > 1975:  # Accounting for omission note
            entities.pop()
            omitted += 1
        entities.append(f"-# Omitted {omitted} mention" + ("s" * (omitted > 1)))

    return "\n".join(dict.fromkeys(entities)), len(entities)


async def remove_button_after_timeout(message: discord.Message) -> None:
    await asyncio.sleep(30)
    with suppress(discord.NotFound, discord.HTTPException):
        await message.edit(view=None)


async def handle_entities(message: Message) -> None:
    if message.author.bot or message.type in IGNORED_MESSAGE_TYPES:
        return

    if is_dm(message.author):
        await try_dm(
            message.author,
            "You can only mention entities in the Ghostty server.",
        )
        return

    msg_content, entity_count = _get_entities(message)

    if not entity_count:
        return

    sent_message = await message.reply(
        msg_content, mention_author=False, view=DeleteMention(message, entity_count)
    )
    message_to_mentions[message] = sent_message
    await remove_button_after_timeout(sent_message)


def get_discussion(repo: Repository, number: int) -> SimpleNamespace:
    _, response = repo._requester.requestJsonAndCheck(
        "POST",
        repo._requester.graphql_url,
        input={
            "query": DISCUSSION_QUERY,
            "variables": {
                "number": number,
                "org": config.GITHUB_ORG,
                "repo": repo.name,
            },
        },
    )
    if "errors" in response:
        raise KeyError((repo.name, number))
    data = response["data"]["repository"]["discussion"]
    return SimpleNamespace(
        user=SimpleNamespace(login=data.pop("user")["login"]),
        created_at=dt.datetime.fromisoformat(data.pop("created_at")),
        **data,
    )


@bot.event
async def on_message_delete(message: discord.Message) -> None:
    if message.author.bot:
        _unlink_original_message(message)
    elif (reply := message_to_mentions.get(message)) is not None:
        await reply.delete()


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message) -> None:
    if before.content == after.content:
        return
    if (old_entites := _get_entities(before)) == (new_entities := _get_entities(after)):
        # Message changed but mentions are the same
        return

    if (reply := message_to_mentions.get(before)) is None:
        if not old_entites[1]:
            # There were no mentions before, so treat this as a new message
            await handle_entities(after)
        # The message was removed from the M2M map at some point
        return

    content, count = new_entities
    if not count:
        # All mentions were edited out
        del message_to_mentions[before]
        await reply.delete()
        return

    # If the message was edited (or created, if never edited) more than 24 hours ago,
    # stop reacting to it and remove its M2M entry.
    last_updated = dt.datetime.now(tz=dt.UTC) - (reply.edited_at or reply.created_at)
    if last_updated > dt.timedelta(hours=24):
        del message_to_mentions[before]
        return

    await reply.edit(
        content=content,
        view=DeleteMention(after, count),
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await remove_button_after_timeout(reply)
