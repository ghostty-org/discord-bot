# pyright: reportUnusedFunction=false

from typing import TYPE_CHECKING

from loguru import logger

from app.components.github_integration.commit_types import CommitKey, commit_cache
from app.components.github_integration.webhooks.utils import (
    EmbedContent,
    Footer,
    send_embed,
)
from toolbox.misc import format_event_sender

if TYPE_CHECKING:
    from monalisten import Monalisten, events


def register_hooks(webhook: Monalisten) -> None:
    @webhook.event.commit_comment
    async def comment(event: events.CommitComment) -> None:
        full_sha = event.comment.commit_id
        sha = full_sha[:7]
        logger.info(
            "received a commit comment event for commit {!r} from {}",
            sha,
            format_event_sender(event.sender),
        )

        owner, _, repo_name = event.repository.full_name.partition("/")
        if commit_summary := await commit_cache.get(
            CommitKey(owner, repo_name, full_sha)
        ):
            commit_title = commit_summary.message.splitlines()[0]
        else:
            logger.warning("no commit summary found for {}", full_sha)
            commit_title = "(no commit message found)"

        await send_embed(
            event.sender,
            EmbedContent(
                f"commented on commit `{sha}`",
                event.comment.html_url,
                event.comment.body,
            ),
            Footer("commit", f"Commit {sha}: {commit_title}"),
            origin_repo=event.repository,
        )
