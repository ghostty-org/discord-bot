import time
from typing import TYPE_CHECKING, Literal, NamedTuple
from urllib.parse import urlparse

from loguru import logger
from monalisten import events

from toolbox.misc import URL_REGEX

if TYPE_CHECKING:
    from githubkit_schemas.latest.models import (  # pyright: ignore[reportMissingTypeStubs]
        SimpleUser,
    )

    from app.components.github_integration.webhooks.utils import Footer
    from toolbox.misc import EmbedColor

type AuthorAssociation = Literal[
    "COLLABORATOR",
    "CONTRIBUTOR",
    "FIRST_TIMER",
    "FIRST_TIME_CONTRIBUTOR",
    "MANNEQUIN",
    "MEMBER",
    "NONE",
    "OWNER",
]
type VouchKind = Literal["vouch", "unvouch", "denounce"]
type VouchQueue = dict[int, VouchQueueEntry]

MAINTAINER_ASSOCIATIONS = frozenset[AuthorAssociation]({
    "OWNER",
    "MEMBER",
    "COLLABORATOR",
})
VOUCH_PAST_TENSE: dict[VouchKind, str] = {
    "vouch": "vouched",
    "unvouch": "unvouched",
    "denounce": "denounced",
}
VOUCH_KIND_COLORS: dict[VouchKind, EmbedColor] = {
    "vouch": "blue",
    "unvouch": "orange",
    "denounce": "red",
}
VOUCH_QUEUE_TTL_SECONDS = 3600


class VouchQueueEntry(NamedTuple):
    kind: VouchKind
    actor: SimpleUser
    footer: Footer
    created_at: float


def is_maintainer(author_association: AuthorAssociation) -> bool:
    return author_association in MAINTAINER_ASSOCIATIONS


def find_vouch_command(body: str) -> VouchKind | None:
    if not body.startswith("!"):
        return None
    if (
        command := body.partition(" ")[0].removeprefix("!").strip()
    ) in VOUCH_KIND_COLORS:
        return command
    return None


def cleanup_vouch_queue(vouch_queue: VouchQueue) -> None:
    now = time.monotonic()
    for comment_id in (
        comment_id
        for comment_id, entry in vouch_queue.items()
        if now - entry.created_at > VOUCH_QUEUE_TTL_SECONDS
    ):
        entry = vouch_queue.pop(comment_id)
        logger.warning(
            "removed stale vouch queue entry for comment {comment_id} "
            "(command: {command}, actor: @{actor})",
            comment_id=comment_id,
            command=entry.kind,
            actor=entry.actor.login,
        )


def register_vouch_command(
    vouch_queue: VouchQueue,
    command: VouchKind,
    event: events.IssueCommentCreated | events.DiscussionCommentCreated,
    footer: Footer,
) -> bool:
    number = (
        event.issue.number
        if isinstance(event, events.IssueCommentCreated)
        else event.discussion.number
    )
    author_association: AuthorAssociation = event.comment.author_association
    if not is_maintainer(author_association):
        logger.warning(
            "ignoring vouch command from non-maintainer @{user} "
            "(association: {assoc}) in #{entity_id}",
            user=event.sender.login,
            assoc=author_association,
            entity_id=number,
        )
        return False

    logger.info(
        "registered vouch system command from @{user} in #{entity_id}",
        user=event.sender.login,
        entity_id=number,
    )
    vouch_queue[event.comment.id] = VouchQueueEntry(
        command, event.sender, footer, time.monotonic()
    )
    return True


def extract_vouch_details(body: str | None) -> tuple[str, int, int, str] | None:
    # Example PR description (wrapped):
    # Triggered by [comment](https://github.com/ghostty-org/ghostty/issues/9999#issuecom
    # ment-3210987654) from @barfoo.
    #
    # Vouch: @foobar
    if body is None or not (match := URL_REGEX.search(body)):
        return None
    comment_url = match[0].rstrip(")")
    parsed_comment = urlparse(comment_url)
    entity_id = parsed_comment.path.split("/")[-1]
    comment_id = parsed_comment.fragment.split("-")[-1]
    _, _, vouchee = body.rpartition("@")
    return comment_url, int(entity_id), int(comment_id), vouchee


def is_vouch_pr(ev: events.PullRequestOpened | events.PullRequestClosed) -> bool:
    return (
        ev.sender.type == "Bot"
        and ev.pull_request.title == "Update VOUCHED list"
        and ev.sender.login == "ghostty-vouch[bot]"
    )
