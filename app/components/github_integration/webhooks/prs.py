# pyright: reportUnusedFunction=false

import asyncio
from itertools import dropwhile
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from loguru import logger

from app.components.github_integration.models import GitHubUser
from app.components.github_integration.webhooks.review_summary import (
    handle_review_request,
)
from app.components.github_integration.webhooks.utils import (
    EmbedContent,
    Footer,
    send_edit_difference,
    send_embed,
)
from app.components.github_integration.webhooks.vouch import (
    VOUCH_KIND_COLORS,
    VOUCH_PAST_TENSE,
    cleanup_vouch_queue,
    extract_vouch_details,
    is_vouch_pr,
)
from toolbox.github import format_event_sender, prettify_suggestions

if TYPE_CHECKING:
    from monalisten import Monalisten, events

    from app.bot import EmojiName
    from app.components.github_integration.webhooks.review_summary import (
        ReviewPools,
        ReviewRequestsModified,
    )
    from app.components.github_integration.webhooks.vouch import VouchQueue

# This looks like a silly const but I wanted to have a single place to document this:
# it looks like GitHub special-cases Copilot, and while the REST API says its login is
# `copilot-pull-request-reviewer[bot]`, webhook events actually just use `Copilot`.
COPILOT_LOGIN = "Copilot"
HUNK_TEMPLATE = "```diff\n{hunk}\n```\n\n{content}"
HUNK_CODEBLOCK_OVERHEAD = len("```diff\n\n```\n\n")


class PRLike(Protocol):
    number: int
    title: str
    html_url: str
    draft: Any
    merged_at: Any
    state: Any


def pr_footer(
    pr: PRLike, /, *, emoji: EmojiName | None = None, from_review: bool = False
) -> Footer:
    if emoji is None:
        # pull_request_review(_comment) events have pull_request objects that don't have
        # the .merged field, so we have to fall back to checking if .merged_at is truthy
        merged = pr.merged_at is not None if from_review else cast("Any", pr).merged
        state = cast("Literal['open', 'closed']", pr.state)
        emoji = "pull_" + ("draft" if pr.draft else "merged" if merged else state)
    return Footer(emoji, f"PR #{pr.number}: {pr.title}")


def pr_embed_content(
    pr: PRLike,
    template: str,
    body: str | None = None,
    /,
    *,
    description: str | None = None,
) -> EmbedContent:
    return EmbedContent(
        template.format(f"PR #{pr.number}"), pr.html_url, body, description
    )


def register_hooks(  # noqa: C901, PLR0915
    webhook: Monalisten,
    tasks: set[asyncio.Task[None]],
    vouch_queue: VouchQueue,
    review_pools: ReviewPools,
) -> None:
    @webhook.event.pull_request
    async def log_event(event: events.PullRequest) -> None:
        logger.info(
            "received event {action!r} for PR #{pr} from {user}",
            action=event.action,
            pr=event.pull_request.number,
            user=format_event_sender(event.sender),
        )

    @webhook.event.pull_request_review
    async def log_review_event(event: events.PullRequestReview) -> None:
        logger.info(
            "received a 'review {action}' event for PR #{pr} from {user}",
            action=event.action,
            pr=event.pull_request.number,
            user=format_event_sender(event.sender),
        )

    @webhook.event.pull_request_review_comment
    async def log_review_comment_event(event: events.PullRequestReviewComment) -> None:
        logger.info(
            "received a 'review comment {action}' event for PR #{pr} from {user}",
            action=event.action,
            pr=event.pull_request.number,
            user=format_event_sender(event.sender),
        )

    @webhook.event.pull_request.opened
    async def opened(event: events.PullRequestOpened) -> None:
        pr = event.pull_request
        if is_vouch_pr(event):
            logger.info(
                "ignoring vouch system PR #{pr} opened by @{user}",
                pr=pr.number,
                user=event.sender.login,
            )
            return

        await send_embed(
            event.sender,
            pr_embed_content(pr, "opened {}", pr.body),
            pr_footer(pr),
            color="green",
            origin_repo=event.repository,
        )

    @webhook.event.pull_request.closed
    async def closed(event: events.PullRequestClosed) -> None:
        cleanup_vouch_queue(vouch_queue)

        pr = event.pull_request
        action, color = ("merged", "purple") if pr.merged else ("closed", "red")
        if not is_vouch_pr(event):
            await send_embed(
                event.sender,
                pr_embed_content(pr, f"{action} {{}}"),
                pr_footer(pr, emoji="pull_" + action),
                color=color,
                origin_repo=event.repository,
            )
            return

        if not (vouch_details := extract_vouch_details(pr.body)):
            logger.error("failed to extract vouch data from PR #{pr}", pr=pr.number)
            return

        url, entity_id, comment_id, vouchee = vouch_details
        if comment_id not in vouch_queue:
            logger.error(
                "missing vouch queue entry for comment {comment} in #{entity}",
                comment=comment_id,
                entity=entity_id,
            )
            return

        if action == "closed":
            logger.warning(
                "vouch PR #{pr} was closed without merge, "
                "cleaning up queue entry for comment {comment}",
                pr=pr.number,
                comment=comment_id,
            )
            return

        kind, actor, footer, _ = vouch_queue.pop(comment_id)
        action_past = VOUCH_PAST_TENSE[kind]
        content = EmbedContent(f"{action_past} @{vouchee} in #{entity_id}", url)
        await send_embed(actor, content, footer, color=VOUCH_KIND_COLORS[kind])

    @webhook.event.pull_request.reopened
    async def reopened(event: events.PullRequestReopened) -> None:
        pr = event.pull_request
        await send_embed(
            event.sender,
            pr_embed_content(pr, "reopened {}"),
            pr_footer(pr, emoji="pull_open"),
            color="green",
        )

    @webhook.event.pull_request.edited
    async def edited(event: events.PullRequestEdited) -> None:
        await send_edit_difference(event, pr_embed_content, pr_footer)

    @webhook.event.pull_request.converted_to_draft
    async def converted_to_draft(event: events.PullRequestConvertedToDraft) -> None:
        pr = event.pull_request
        await send_embed(
            event.sender,
            pr_embed_content(pr, "converted {} to draft"),
            pr_footer(pr, emoji="pull_draft"),
            color="gray",
        )

    @webhook.event.pull_request.ready_for_review
    async def ready_for_review(event: events.PullRequestReadyForReview) -> None:
        pr = event.pull_request
        await send_embed(
            event.sender,
            pr_embed_content(pr, "marked {} as ready for review"),
            pr_footer(pr, emoji="pull_open"),
            color="green",
        )

    @webhook.event.pull_request.locked
    async def locked(event: events.PullRequestLocked) -> None:
        pr = event.pull_request
        template = "locked {}"
        if reason := pr.active_lock_reason:
            template += f" as {reason}"
        await send_embed(
            event.sender,
            pr_embed_content(pr, template),
            pr_footer(pr),
            color="orange",
        )

    @webhook.event.pull_request.unlocked
    async def unlocked(event: events.PullRequestUnlocked) -> None:
        pr = event.pull_request
        await send_embed(
            event.sender,
            pr_embed_content(pr, "unlocked {}"),
            pr_footer(pr),
            color="blue",
        )

    @webhook.event.pull_request.review_requested  # pyright: ignore[reportArgumentType]
    @webhook.event.pull_request.review_request_removed
    async def review_requests_modified(event: ReviewRequestsModified) -> None:
        async def run() -> None:
            pr = event.pull_request
            if summary := await handle_review_request(review_pools, event):
                title, body = summary.format()
                await send_embed(
                    event.sender,
                    pr_embed_content(pr, f"{title} for {{}}", description=body),
                    pr_footer(pr),
                )

        task = asyncio.create_task(run())
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    @webhook.event.pull_request_review.submitted
    async def submitted(event: events.PullRequestReviewSubmitted) -> None:
        pr, review = event.pull_request, event.review

        if review.state == "commented" and not review.body:
            # We most definitely have some pull_request_review_comment event(s)
            # happening at the same time, so an empty review like this can be ignored to
            # reduce spam.
            return

        if event.sender.login == COPILOT_LOGIN:
            # The bodies of Copilot reviews are usually verbose (and often trash),
            # so just drop it.
            review.body = ""

        match review.state:
            case "approved":
                color, title = "green", "approved"
            case "commented":
                color, title = None, "reviewed"
            case "changes_requested":
                color, title = "red", "requested changes in"
            case s:
                logger.warning("unexpected review state: {state}", state=s)
                return

        emoji = "pull_" + (
            "draft" if pr.draft else "merged" if pr.merged_at else pr.state
        )
        await send_embed(
            event.sender,
            EmbedContent(f"{title} PR #{pr.number}", review.html_url, review.body),
            pr_footer(pr, emoji=emoji),
            color=color,
            origin_repo=event.repository,
        )

    @webhook.event.pull_request_review.dismissed
    async def dismissed(event: events.PullRequestReviewDismissed) -> None:
        pr = event.pull_request
        emoji = "pull_" + (
            "draft" if pr.draft else "merged" if pr.merged_at else pr.state
        )
        review_author = (
            GitHubUser(**event.review.user.model_dump())
            if event.review.user
            else GitHubUser.default()
        )
        await send_embed(
            event.sender,
            pr_embed_content(
                pr, "dismissed a review of {}", f"authored by {review_author.format()}"
            ),
            pr_footer(pr, emoji=emoji),
            color="orange",
        )

    @webhook.event.pull_request_review_comment.created
    async def created(event: events.PullRequestReviewCommentCreated) -> None:
        pr, content = event.pull_request, prettify_suggestions(event.comment)
        if no_suggestions_present := content is None:
            content = event.comment.body

        if event.sender.login == COPILOT_LOGIN:
            # Ignore, we don't need the spam.
            logger.info("Copilot review comment dropped")
            return

        hunk = _reduce_diff_hunk(event.comment.diff_hunk)
        hunk_can_fit = 500 - len(content) - len(hunk) - HUNK_CODEBLOCK_OVERHEAD >= 0
        if hunk.strip() and hunk_can_fit and no_suggestions_present:
            content = HUNK_TEMPLATE.format(hunk=hunk, content=content)

        await send_embed(
            event.sender,
            EmbedContent(
                f"left a review comment on PR #{pr.number}",
                event.comment.html_url,
                content,
            ),
            pr_footer(pr, from_review=True),
            origin_repo=event.repository,
        )


def _reduce_diff_hunk(hunk: str) -> str:
    def missing_diff_marker(line: str) -> bool:
        return not line.startswith(("-", "+"))

    hunk_lines = [*dropwhile(missing_diff_marker, hunk.splitlines())]
    return "\n".join([*dropwhile(missing_diff_marker, hunk_lines[::-1])][::-1])
