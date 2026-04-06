# pyright: reportPrivateUsage=false

import asyncio
from unittest.mock import Mock

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from monalisten.events import PullRequestReviewRequested as PRReviewReq
from monalisten.events import PullRequestReviewRequestRemoved as PRReviewReqRm

from tests.webhooks.utils import (
    DEFAULT_PR_SENDER_ID,
    add_pr_metadata,
    dummy_user,
    github_teams,
    github_users,
    review_request_modification_events,
    review_request_summaries,
    reviewers,
    team_review_request,
    unknown_review_request,
    user_review_request,
)

from app.components.github_integration.models import GitHubTeam, GitHubUser
from app.components.github_integration.webhooks.review_summary import (
    Reviewer,
    ReviewPoolKey,
    ReviewPools,
    ReviewRequestsModified,
    ReviewRequestSummary,
    _parse_reviewer,
    handle_review_request,
)
from toolbox.misc import seq_to_aiter


def test_empty_review_request_summary_falsy() -> None:
    assert not ReviewRequestSummary()


@given(github_users())
def test_parse_reviewer_user(user: GitHubUser) -> None:
    event = user_review_request(
        name=user.name, html_url=user.url, avatar_url=user.icon_url
    )
    assert _parse_reviewer(event) == user


@given(github_teams())
def test_parse_reviewer_team(team: GitHubTeam) -> None:
    assert _parse_reviewer(team_review_request(name=team.name)) == team


def test_parse_reviewer_none() -> None:
    assert _parse_reviewer(Mock(())) is None


@settings(max_examples=25)
@given(st.lists(review_request_modification_events(include_unknowns=False)))
async def test_collect_review_request_summary_contains_all_reviewers(
    requests: list[ReviewRequestsModified],
) -> None:
    reviewers = set(map(_parse_reviewer, requests))
    s = await ReviewRequestSummary.collect(seq_to_aiter(requests))
    assert s.requests | s.removals | s.accidental_requests | s.rerequests == reviewers


@settings(max_examples=25)
@given(st.lists(review_request_modification_events()))
async def test_collect_review_request_summary_has_no_duplicate_reviewers(
    requests: list[ReviewRequestsModified],
) -> None:
    s = await ReviewRequestSummary.collect(seq_to_aiter(requests))
    assert len(s.requests | s.removals | s.accidental_requests | s.rerequests) == (
        len(s.requests)
        + len(s.removals)
        + len(s.accidental_requests)
        + len(s.rerequests)
    )


REVIEW_REQUEST_COLLECTION_TESTS = [
    (
        [user_review_request(PRReviewReq, name="foo")],
        ReviewRequestSummary(requests={dummy_user(name="foo")}),
    ),
    (
        [team_review_request(PRReviewReq, name="ghostty-org/spook")],
        ReviewRequestSummary(requests={GitHubTeam(name="ghostty-org/spook")}),
    ),
    (
        [
            user_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReqRm, name="bar"),
        ],
        ReviewRequestSummary(removals={dummy_user(name="foo"), GitHubTeam(name="bar")}),
    ),
    (
        [
            team_review_request(PRReviewReq, name="foo"),
            user_review_request(PRReviewReqRm, name="bar"),
        ],
        ReviewRequestSummary(
            requests={GitHubTeam(name="foo")}, removals={dummy_user(name="bar")}
        ),
    ),
    (
        [
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(accidental_requests={GitHubTeam(name="foo")}),
    ),
    (
        [
            user_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(
            requests={dummy_user(name="foo")}, removals={GitHubTeam(name="foo")}
        ),
    ),
    (
        [
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="bar"),
            team_review_request(PRReviewReq, name="baz"),
        ],
        ReviewRequestSummary(
            requests={GitHubTeam(name="baz")},
            removals={GitHubTeam(name="bar")},
            rerequests={dummy_user(name="foo")},
        ),
    ),
    (
        [
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(removals={dummy_user(name="foo")}),
    ),
    (
        [
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
        ],
        ReviewRequestSummary(requests={GitHubTeam(name="foo")}),
    ),
    (
        [
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReq, name="foo"),
            user_review_request(PRReviewReq, name="foo"),
        ],
        ReviewRequestSummary(rerequests={dummy_user(name="foo")}),
    ),
    (
        [
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(accidental_requests={GitHubTeam(name="foo")}),
    ),
    (
        [
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
        ],
        ReviewRequestSummary(requests={GitHubTeam(name="foo")}),
    ),
    (
        [
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReq, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReq, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(removals={dummy_user(name="foo")}),
    ),
    (
        [
            user_review_request(PRReviewReq, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
            user_review_request(PRReviewReq, name="foo"),
            user_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(accidental_requests={dummy_user(name="foo")}),
    ),
    (
        [
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
        ],
        ReviewRequestSummary(rerequests={GitHubTeam(name="foo")}),
    ),
    (
        [
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
            team_review_request(PRReviewReq, name="foo"),
            team_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(removals={GitHubTeam(name="foo")}),
    ),
    (
        [
            user_review_request(PRReviewReq, name="bar"),
            user_review_request(PRReviewReqRm, name="bar"),
            user_review_request(PRReviewReqRm, name="bar"),
            user_review_request(PRReviewReqRm, name="bar"),
            user_review_request(PRReviewReq, name="bar"),
            user_review_request(PRReviewReqRm, name="bar"),
        ],
        ReviewRequestSummary(accidental_requests={dummy_user(name="bar")}),
    ),
    (
        [
            unknown_review_request(PRReviewReq),
            unknown_review_request(PRReviewReq),
            user_review_request(PRReviewReq, name="foo"),
            unknown_review_request(PRReviewReq),
            team_review_request(PRReviewReqRm, name="foo"),
        ],
        ReviewRequestSummary(
            requests={dummy_user(name="foo")},
            removals={GitHubTeam(name="foo")},
            unknown_requests=3,
        ),
    ),
    (
        [
            unknown_review_request(PRReviewReqRm),
            unknown_review_request(PRReviewReqRm),
            unknown_review_request(PRReviewReq),
            user_review_request(PRReviewReqRm, name="foo"),
            unknown_review_request(PRReviewReq),
        ],
        ReviewRequestSummary(
            removals={dummy_user(name="foo")},
            unknown_requests=2,
            unknown_removals=2,
        ),
    ),
]


@pytest.mark.parametrize(
    ("requests", "result"),
    [([], ReviewRequestSummary()), *REVIEW_REQUEST_COLLECTION_TESTS],
)
async def test_collect_review_request_summary(
    requests: list[Mock], result: ReviewRequestSummary
) -> None:
    assert await ReviewRequestSummary.collect(seq_to_aiter(requests)) == result


# Since handle_review_request is just synchronization glue around
# ReviewRequestSummary.collect, the same tests should produce the same results.
@pytest.mark.parametrize(("requests", "result"), REVIEW_REQUEST_COLLECTION_TESTS)
async def test_handle_review_request_collection(
    requests: list[Mock], result: ReviewRequestSummary
) -> None:
    pools: ReviewPools = {}
    await run_review_request_collection_test(pools, 12, requests, result)


# Same as the test above, except in parallel, to catch cases where having multiple PRs
# in the queue makes it malfunction (i.e.: bugs caused by accidental dependencies
# between separate PRs). The other test has MUCH better error messages, so both shall be
# run instead of only this one, despite this one being a superset of the other one.
@settings(max_examples=10)
@given(st.permutations(REVIEW_REQUEST_COLLECTION_TESTS))
async def test_handle_review_request_parallel_collection(
    tests: list[tuple[list[Mock], ReviewRequestSummary]],
) -> None:
    pools: ReviewPools = {}
    async with asyncio.TaskGroup() as group:
        for pr, (requests, result) in enumerate(tests, 1):
            group.create_task(
                run_review_request_collection_test(pools, pr, requests, result)
            )


async def run_review_request_collection_test(
    pools: ReviewPools,
    pr_number: int,
    requests: list[Mock],
    result: ReviewRequestSummary,
) -> None:
    first, *rest = (add_pr_metadata(m, pr_number) for m in requests)

    async def enqueue() -> None:
        for r in rest:
            rv = await handle_review_request(pools, r, timeout=None)
            assert rv is None
            # Context switch unnecessarily to make sure things truly run in parallel in
            # the parallel collection test. (Based on viewing the logs in failed cases,
            # the scheduler does turn out to be too smart for our test without this.)
            await asyncio.sleep(0)
        # Explicitly shut down the queue.
        key = ReviewPoolKey(pr_number=pr_number, actor_id=DEFAULT_PR_SENDER_ID)
        pools.pop(key).shutdown()
        await asyncio.sleep(0)

    async with asyncio.TaskGroup() as group:
        summary = group.create_task(handle_review_request(pools, first, timeout=None))
        group.create_task(enqueue())

    assert summary.result() == result


@given(st.none() | st.text())
def test_format_reviewers_empty(heading: str | None) -> None:
    assert ReviewRequestSummary._format_reviewers(set(), 0, heading=heading) == ""


@settings(max_examples=50)
@given(st.sets(reviewers()), st.integers(min_value=1), st.none() | st.text())
def test_format_reviewers_contains_reviewers(
    reviewers: set[Reviewer], unknown: int, heading: str | None
) -> None:
    formatted = ReviewRequestSummary._format_reviewers(
        reviewers, unknown, heading=heading
    )
    for r in reviewers:
        assert r.format() in formatted


@settings(max_examples=50)
@given(st.sets(reviewers()), st.integers(min_value=1), st.none() | st.text())
def test_format_reviewers_contains_unknown_count(
    reviewers: set[Reviewer], unknown: int, heading: str | None
) -> None:
    assert f"{unknown} unknown" in ReviewRequestSummary._format_reviewers(
        reviewers, unknown, heading=heading
    )


@settings(max_examples=50)
@given(st.sets(reviewers()), st.integers(min_value=0), st.text())
def test_format_reviewers_contains_heading(
    reviewers: set[Reviewer], unknown: int, heading: str
) -> None:
    assume(reviewers or unknown)
    assert heading in ReviewRequestSummary._format_reviewers(
        reviewers, unknown, heading=heading
    )


@settings(max_examples=50)
@given(reviewers().filter(lambda r: "\n" not in r.format()))
def test_format_reviewers_single_reviewer_is_single_line(reviewer: Reviewer) -> None:
    assert "\n" not in ReviewRequestSummary._format_reviewers({reviewer}, 0)


@given(st.integers(min_value=1))
def test_format_reviewers_unknown_only_is_single_line(unknown: int) -> None:
    assert "\n" not in ReviewRequestSummary._format_reviewers(set(), unknown)


@settings(max_examples=50)
@given(
    st.sets(reviewers().filter(lambda r: "\n" not in r.format()), min_size=2),
    st.integers(min_value=0),
)
def test_format_reviewers_multiple_reviewers_on_multiple_lines(
    reviewers: set[Reviewer], unknown: int
) -> None:
    assert "\n" in ReviewRequestSummary._format_reviewers(reviewers, unknown)


@settings(max_examples=50)
@given(
    st.sets(reviewers().filter(lambda r: "\n" not in r.format()), min_size=1),
    st.integers(min_value=1),
)
def test_format_reviewers_reviewer_and_unknown_on_multiple_lines(
    reviewers: set[Reviewer], unknown: int
) -> None:
    assert "\n" in ReviewRequestSummary._format_reviewers(reviewers, unknown)


@settings(max_examples=50)
@given(review_request_summaries())
def test_format_review_request_summary_has_all_reviewers(
    s: ReviewRequestSummary,
) -> None:
    _, body = s.format()
    for r in s.requests | s.removals | s.accidental_requests | s.rerequests:
        assert r.format() in body
    if n := s.unknown_requests:
        assert f"{n} unknown" in body
    if n := s.unknown_removals:
        assert f"{n} unknown" in body


def test_format_empty_review_request_summary() -> None:
    assert ReviewRequestSummary().format() == ("updated review requests", "")


@pytest.mark.parametrize(
    ("summary", "expected_title", "expected_body"),
    [
        (
            ReviewRequestSummary(requests={dummy_user(name="")}),
            "requested review",
            "from [``](<>)",
        ),
        (
            ReviewRequestSummary(requests={GitHubTeam(name="")}),
            "requested review",
            "from the `` team",
        ),
        (
            ReviewRequestSummary(unknown_requests=13),
            "requested review",
            "from 13 unknown users",
        ),
        (
            ReviewRequestSummary(requests={dummy_user(name="")}, unknown_requests=23),
            "requested review",
            "from:\n- [``](<>)\n- 23 unknown users",
        ),
        (
            ReviewRequestSummary(requests={dummy_user(name="a"), dummy_user(name="b")}),
            "requested review",
            "from:\n- [`a`](<>)\n- [`b`](<>)",
        ),
        (
            ReviewRequestSummary(
                requests={dummy_user(name="b"), dummy_user(name="a")},
                unknown_requests=31,
            ),
            "requested review",
            "from:\n- [`a`](<>)\n- [`b`](<>)\n- 31 unknown users",
        ),
        (
            ReviewRequestSummary(
                requests={GitHubTeam(name="b"), dummy_user(name="a")},
                unknown_requests=6,
            ),
            "requested review",
            "from:\n- [`a`](<>)\n- the `b` team\n- 6 unknown users",
        ),
        (
            ReviewRequestSummary(removals={dummy_user(name="")}),
            "removed review request",
            "from [``](<>)",
        ),
        (
            ReviewRequestSummary(removals={GitHubTeam(name="")}),
            "removed review request",
            "from the `` team",
        ),
        (
            ReviewRequestSummary(unknown_removals=9),
            "removed review request",
            "from 9 unknown users",
        ),
        (
            ReviewRequestSummary(removals={dummy_user(name="")}, unknown_removals=22),
            "removed review request",
            "from:\n- [``](<>)\n- 22 unknown users",
        ),
        (
            ReviewRequestSummary(removals={dummy_user(name="a"), dummy_user(name="b")}),
            "removed review request",
            "from:\n- [`a`](<>)\n- [`b`](<>)",
        ),
        (
            ReviewRequestSummary(
                removals={dummy_user(name="a"), dummy_user(name="b")},
                unknown_removals=10000,
            ),
            "removed review request",
            "from:\n- [`a`](<>)\n- [`b`](<>)\n- 10000 unknown users",
        ),
        (
            ReviewRequestSummary(
                removals={dummy_user(name="a"), GitHubTeam(name="b")},
                unknown_removals=3,
            ),
            "removed review request",
            "from:\n- [`a`](<>)\n- the `b` team\n- 3 unknown users",
        ),
        (
            ReviewRequestSummary(accidental_requests={dummy_user(name="")}),
            "updated review requests",
            "**Accidentally requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(accidental_requests={GitHubTeam(name="")}),
            "updated review requests",
            "**Accidentally requested review** from the `` team",
        ),
        (
            ReviewRequestSummary(
                accidental_requests={GitHubTeam(name="a"), dummy_user(name="b")}
            ),
            "updated review requests",
            "**Accidentally requested review** from:\n- the `a` team\n- [`b`](<>)",
        ),
        (
            ReviewRequestSummary(rerequests={dummy_user(name="")}),
            "updated review requests",
            "**Removed, then requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(rerequests={GitHubTeam(name="")}),
            "updated review requests",
            "**Removed, then requested review** from the `` team",
        ),
        (
            ReviewRequestSummary(
                rerequests={GitHubTeam(name="b"), dummy_user(name="a")}
            ),
            "updated review requests",
            "**Removed, then requested review** from:\n- [`a`](<>)\n- the `b` team",
        ),
    ],
)
def test_format_review_request_summary_simple(
    summary: ReviewRequestSummary, expected_title: str, expected_body: str
) -> None:
    title, body = summary.format()
    assert title == expected_title
    assert body == expected_body


@pytest.mark.parametrize(
    ("summary", "expected_body"),
    [
        (
            ReviewRequestSummary(
                requests={dummy_user(name="")},
                accidental_requests={dummy_user(name="")},
            ),
            "**Requested review** from [``](<>)\n\n"
            "**Accidentally requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(
                accidental_requests={GitHubTeam(name="")}, unknown_requests=44
            ),
            "**Requested review** from 44 unknown users\n\n"
            "**Accidentally requested review** from the `` team",
        ),
        (
            ReviewRequestSummary(
                removals={GitHubTeam(name="")},
                accidental_requests={dummy_user(name="")},
            ),
            "**Removed review request** from the `` team\n\n"
            "**Accidentally requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(
                requests={dummy_user(name="")}, rerequests={GitHubTeam(name="")}
            ),
            "**Requested review** from [``](<>)\n\n"
            "**Removed, then requested review** from the `` team",
        ),
        (
            ReviewRequestSummary(
                removals={dummy_user(name="")}, rerequests={dummy_user(name="")}
            ),
            "**Removed review request** from [``](<>)\n\n"
            "**Removed, then requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(rerequests={dummy_user(name="")}, unknown_removals=17),
            "**Removed review request** from 17 unknown users\n\n"
            "**Removed, then requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(
                requests={dummy_user(name="")}, removals={dummy_user(name="")}
            ),
            "**Requested review** from [``](<>)\n\n"
            "**Removed review request** from [``](<>)",
        ),
        (
            ReviewRequestSummary(removals={GitHubTeam(name="")}, unknown_requests=678),
            "**Requested review** from 678 unknown users\n\n"
            "**Removed review request** from the `` team",
        ),
        (
            ReviewRequestSummary(requests={dummy_user(name="")}, unknown_removals=-3),
            "**Requested review** from [``](<>)\n\n"
            "**Removed review request** from -3 unknown users",
        ),
        (
            ReviewRequestSummary(unknown_requests=12, unknown_removals=55),
            "**Requested review** from 12 unknown users\n\n"
            "**Removed review request** from 55 unknown users",
        ),
        (
            ReviewRequestSummary(
                accidental_requests={GitHubTeam(name="")},
                rerequests={dummy_user(name="")},
            ),
            "**Accidentally requested review** from the `` team\n\n"
            "**Removed, then requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(
                requests={GitHubTeam(name="")},
                removals={GitHubTeam(name="")},
                accidental_requests={dummy_user(name="")},
            ),
            "**Requested review** from the `` team\n\n"
            "**Removed review request** from the `` team\n\n"
            "**Accidentally requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(
                removals={dummy_user(name="")},
                accidental_requests={GitHubTeam(name="")},
                rerequests={dummy_user(name="")},
                unknown_requests=16,
            ),
            "**Requested review** from 16 unknown users\n\n"
            "**Removed review request** from [``](<>)\n\n"
            "**Accidentally requested review** from the `` team\n\n"
            "**Removed, then requested review** from [``](<>)",
        ),
        (
            ReviewRequestSummary(
                requests={dummy_user(name="a"), dummy_user(name="b")},
                removals={
                    GitHubTeam(name="b"),
                    dummy_user(name="c"),
                    dummy_user(name="a"),
                },
                rerequests={GitHubTeam(name="g")},
                unknown_requests=13,
                unknown_removals=4,
            ),
            "**Requested review** from:\n- [`a`](<>)\n- [`b`](<>)"
            "\n- 13 unknown users\n\n"
            "**Removed review request** from:\n- [`a`](<>)\n- the `b` team"
            "\n- [`c`](<>)\n- 4 unknown users\n\n"
            "**Removed, then requested review** from the `g` team",
        ),
        (
            ReviewRequestSummary(
                removals={dummy_user(name="b"), GitHubTeam(name="a")},
                accidental_requests={GitHubTeam(name="c")},
                unknown_requests=44,
            ),
            "**Requested review** from 44 unknown users\n\n"
            "**Removed review request** from:\n- the `a` team\n- [`b`](<>)\n\n"
            "**Accidentally requested review** from the `c` team",
        ),
        (
            ReviewRequestSummary(
                requests={
                    GitHubTeam(name="c"),
                    dummy_user(name="a"),
                    GitHubTeam(name="b"),
                },
                removals={dummy_user(name="a"), dummy_user(name="b")},
                accidental_requests={dummy_user(name="d"), GitHubTeam(name="e")},
                rerequests={GitHubTeam(name="r"), GitHubTeam(name="q")},
                unknown_requests=21,
            ),
            "**Requested review** from:\n- [`a`](<>)\n- the `b` team\n- the `c` team"
            "\n- 21 unknown users\n\n"
            "**Removed review request** from:\n- [`a`](<>)\n- [`b`](<>)\n\n"
            "**Accidentally requested review** from:\n- [`d`](<>)\n- the `e` team\n\n"
            "**Removed, then requested review** from:\n- the `q` team\n- the `r` team",
        ),
    ],
)
def test_format_review_request_summary_complex(
    summary: ReviewRequestSummary, expected_body: str
) -> None:
    title, body = summary.format()
    assert title == "updated review requests"
    assert body == expected_body
