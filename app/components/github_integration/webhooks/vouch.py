from typing import TYPE_CHECKING, Literal, NamedTuple
from urllib.parse import urlparse

from toolbox.misc import URL_REGEX

if TYPE_CHECKING:
    from githubkit.versions.latest.models import SimpleUser
    from monalisten import events

    from app.components.github_integration.webhooks.utils import EmbedColor, Footer

type VouchKind = Literal["vouch", "unvouch", "denounce"]
type VouchQueue = dict[int, VouchQueueEntry]

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


class VouchQueueEntry(NamedTuple):
    kind: VouchKind
    actor: SimpleUser
    footer: Footer


def find_vouch_command(body: str) -> VouchKind | None:
    if not body.startswith("!"):
        return None
    if (command := body.partition(" ")[0].removeprefix("!")) in VOUCH_KIND_COLORS:
        return command
    return None


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
    return ev.sender.type == "User" and ev.pull_request.title == "Update VOUCHED list"
