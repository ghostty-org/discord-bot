import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple, Self

from loguru import logger
from monalisten import events

from app.components.github_integration.models import GitHubTeam, GitHubUser
from toolbox.misc import drain_queue

if TYPE_CHECKING:
    from collections.abc import AsyncIterable


REVIEW_REQUEST_GROUP_TIMEOUT = 5  # seconds


type Reviewer = GitHubUser | GitHubTeam
type ReviewRequestsModified = (
    events.PullRequestReviewRequested | events.PullRequestReviewRequestRemoved
)
type ReviewPools = dict[ReviewPoolKey, asyncio.Queue[ReviewRequestsModified]]


class ReviewPoolKey(NamedTuple):
    """
    The minimum amount of data needed to differentiate semantic groups of review
    requests or removals.
    """

    pr_number: int
    actor_id: int


async def handle_review_request(
    review_pools: ReviewPools,
    event: ReviewRequestsModified,
    *,
    timeout: int | None = REVIEW_REQUEST_GROUP_TIMEOUT,  # noqa: ASYNC109
) -> ReviewRequestSummary | None:
    key = ReviewPoolKey(pr_number=event.pull_request.number, actor_id=event.sender.id)

    # If we already have a queue for this PR+user combination, simply collect to it.
    if q := review_pools.get(key):
        logger.info("found existing review pool for key {key}", key=key)
        await q.put(event)
        return None

    logger.info(
        "creating new review pool #{n} for key {key}", n=len(review_pools) + 1, key=key
    )
    q = asyncio.Queue[ReviewRequestsModified]()
    review_pools[key] = q
    # This won't throw QueueShutDown as it cannot be shut down yet: the timeout
    # hasn't been set.
    await q.put(event)
    # The coroutine calling this function will see this queue through to the end;
    # future review_request() calls for this queue will terminate immediately after
    # updating the queue.

    async def timer() -> None:
        if timeout is None:
            return
        await asyncio.sleep(timeout)
        del review_pools[key]
        # Signal the timeout to the queue.
        q.shutdown()
        logger.info(
            "shut down review pool {key} ({n} remain)", key=key, n=len(review_pools)
        )

    async with asyncio.TaskGroup() as group:  # transparently handle cancelation.
        group.create_task(timer())
        summary = group.create_task(ReviewRequestSummary.collect(drain_queue(q)))

    return summary.result()


def _parse_reviewer(event: ReviewRequestsModified) -> Reviewer | None:
    # Abusing duck typing here because the API models are insufferable.
    event_dyn: Any = event
    if hasattr(event_dyn, "requested_team"):
        return GitHubTeam(name=event_dyn.requested_team.name)
    if requested_reviewer := getattr(event_dyn, "requested_reviewer", None):
        return GitHubUser(**requested_reviewer.model_dump())
    return None


@dataclass(kw_only=True)
class ReviewRequestSummary:
    requests: set[Reviewer] = field(default_factory=set)
    removals: set[Reviewer] = field(default_factory=set)
    # When a review was requested from somebody, then later removed.
    accidental_requests: set[Reviewer] = field(default_factory=set)
    # When a review request for somebody was removed, then later re-requested.
    rerequests: set[Reviewer] = field(default_factory=set)
    unknown_requests: int = 0  # count.
    unknown_removals: int = 0  # count.

    def __bool__(self) -> bool:
        return bool(
            self.requests
            or self.removals
            or self.accidental_requests
            or self.rerequests
            or self.unknown_requests
            or self.unknown_removals
        )

    @staticmethod
    def _categorize(
        r: Reviewer,
        *,
        default_set: set[Reviewer],
        opposite_set: set[Reviewer],
        null_set: set[Reviewer],
        opposite_null_set: set[Reviewer],
    ) -> None:
        """
        Categorize a reviewer given its event and the opposite event's sets. This
        function mutates the passed sets.

        Arguments:
            default_set -- The set associated with this event (`removals`/`requests`).
            opposite_set -- The set associated with the opposite event (`removals` for
                requests; `requests` for removals).
            null_set -- The set associated with events of this type that were later
                undone; i.e.: requesting a review then removing it again (represented by
                `accidental_requests`), or removing a request then requesting it again
                (represented by `rerequests`).
            opposite_null_set -- Likewise, but for the opposite event.

        Note that the null sets are sets of reviewers with a null (zero *delta*, and
        aren't always-null (empty) sets.
        """
        # NOTE: an invariant is that every reviewer is only present in one set at
        # a time, which is asserted in every branch below as a precaution.
        if r in null_set:
            # Either:
            #   - a review was requested (r put in `requests`), then removed (r put in
            #     `accidental_requests`), then requested again (this event).
            #   - a review request was removed (r put in `removals`), then requested (r
            #     put in `rerequests`), then removed again (this event).
            # These request/remove cycles can be arbitrarily long, so we'll only show
            # the difference between the initial and final states—that is, we'll undo
            # the previous update which moved it from the default set to the null set.
            for s in (default_set, opposite_set, opposite_null_set):
                assert r not in s
            default_set.add(r)
            null_set.discard(r)
        elif r in opposite_null_set:
            # Either:
            #   - a review request was removed (r put in `removals`), then requested (r
            #     put in `rerequests`), then requested again (this event).
            #   - a review was requested (r put in `requests`), then removed (r put in
            #     `accidental_requests`), then removed again (this event).
            # This is impossible in theory but random chance writes better applications
            # than GitHub, so just ignore it.
            for s in (default_set, opposite_set):
                assert r not in s
            logger.warning(
                "ignoring theoretically impossible duplicate review undo event for {r}",
                r=r.name,
            )
        elif r in opposite_set:
            # Either a review request was removed then requested again, or the opposite.
            # This event is the second one, so we want to move it to the *opposite* null
            # set—that of the *first*.
            assert r not in default_set
            opposite_null_set.add(r)
            opposite_set.discard(r)
        elif r in default_set:
            # A review was requested twice in a row, or a review request was likewise
            # removed. Again, this is impossible in theory, but GitHub's webhook event
            # synchronization is, to say the least, nonexistent.
            logger.warning(
                "ignoring theoretically impossible duplicate review event for {r}",
                r=r.name,
            )
        else:
            default_set.add(r)

    @classmethod
    async def collect(cls, it: AsyncIterable[ReviewRequestsModified]) -> Self:
        summary = cls()
        async for ev in it:
            r = _parse_reviewer(ev)
            if isinstance(ev, events.PullRequestReviewRequested):
                if r is None:
                    summary.unknown_requests += 1
                else:
                    summary._categorize(
                        r,
                        default_set=summary.requests,
                        opposite_set=summary.removals,
                        null_set=summary.accidental_requests,
                        opposite_null_set=summary.rerequests,
                    )
            else:  # noqa: PLR5501 # the symmetry improves clarity.
                if r is None:
                    summary.unknown_removals += 1
                else:
                    summary._categorize(
                        r,
                        default_set=summary.removals,
                        opposite_set=summary.requests,
                        null_set=summary.rerequests,
                        opposite_null_set=summary.accidental_requests,
                    )
        return summary

    @staticmethod
    def _format_reviewers(
        reviewers: set[Reviewer], unknown: int = 0, *, heading: str | None = None
    ) -> str:
        heading_ = f"**{heading}** " * (heading is not None)
        match sorted(reviewers, key=lambda r: r.name):
            case [] if unknown:
                # Only unknowns.
                return f"{heading_}from {unknown} unknown users"
            case []:
                return ""
            # Unknowns go on a separate line, so if there is both a reviewer and
            # unknowns, go down the last case instead so that they're formatted on
            # multiple lines.
            case [reviewer] if not unknown:
                return f"{heading_}from {reviewer.format()}"
            case rs:
                return (
                    f"{heading_}from:\n"
                    + "\n".join(f"- {r.format()}" for r in rs)
                    + (f"\n- {unknown} unknown users" if unknown else "")
                )

    def format(self) -> tuple[str, str]:
        """Return the appropriate title and body, respectively, in a 2-tuple."""
        have_requests = bool(self.requests or self.unknown_requests)
        have_removals = bool(self.removals or self.unknown_removals)
        if (
            self.accidental_requests
            or self.rerequests
            or not (have_requests ^ have_removals)
        ):
            sections = (
                self._format_reviewers(
                    self.requests, self.unknown_requests, heading="Requested review"
                ),
                self._format_reviewers(
                    self.removals,
                    self.unknown_removals,
                    heading="Removed review request",
                ),
                self._format_reviewers(
                    self.accidental_requests, heading="Accidentally requested review"
                ),
                self._format_reviewers(
                    self.rerequests, heading="Removed, then requested review"
                ),
            )
            return "updated review requests", "\n\n".join(filter(None, sections))
        if have_requests:
            return "requested review", self._format_reviewers(
                self.requests, self.unknown_requests
            )
        if have_removals:
            return "removed review request", self._format_reviewers(
                self.removals, self.unknown_removals
            )
        # Fail loudly in case someone messes up when updating the Boolean algebra hell
        # above.
        msg = "unreachable"
        raise AssertionError(msg)
