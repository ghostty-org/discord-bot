from types import UnionType
from typing import TYPE_CHECKING, get_args
from unittest.mock import Mock

from githubkit_schemas.latest.models import SimpleUser
from hypothesis import strategies as st
from monalisten import events

from app.components.github_integration.models import GitHubTeam, GitHubUser
from app.components.github_integration.webhooks.prs import PRLike
from app.components.github_integration.webhooks.review_summary import (
    ReviewRequestsModified,
    ReviewRequestSummary,
)

if TYPE_CHECKING:
    from app.components.github_integration.webhooks.review_summary import Reviewer

DEFAULT_PR_SENDER_ID = 42


def make_user(
    login: str = "testuser",
    url: str = "https://github.com/testuser",
    avatar_url: str = "https://avatars.githubusercontent.com/u/1",
    user_type: str = "User",
    user_id: int = 1,
) -> SimpleUser:
    return Mock(
        SimpleUser,
        login=login,
        html_url=url,
        avatar_url=avatar_url,
        type=user_type,
        id=user_id,
    )


def make_pr(
    number: int = 1,
    title: str = "Test PR",
    state: str = "open",
    draft: bool = False,
    merged: bool = False,
    merged_at: str | None = None,
    html_url: str = "https://github.com/ghostty-org/ghostty/pull/1",
) -> PRLike:
    return Mock(
        PRLike,
        number=number,
        title=title,
        html_url=html_url,
        draft=draft,
        merged=merged,
        merged_at=merged_at,
        state=state,
    )


@st.composite
def github_users(draw: st.DrawFn) -> GitHubUser:
    return GitHubUser(
        login=draw(st.text()),
        url=draw(st.text()),
        icon_url=draw(st.text()),
    )


@st.composite
def github_teams(draw: st.DrawFn) -> GitHubTeam:
    return GitHubTeam(name=draw(st.text()))


def reviewers() -> st.SearchStrategy[Reviewer]:
    return github_teams() | github_users()


@st.composite
def review_request_summaries(draw: st.DrawFn) -> ReviewRequestSummary:
    return ReviewRequestSummary(
        requests=draw(st.sets(reviewers())),
        removals=draw(st.sets(reviewers())),
        accidental_requests=draw(st.sets(reviewers())),
        rerequests=draw(st.sets(reviewers())),
        unknown_requests=draw(st.integers(min_value=0)),
        unknown_removals=draw(st.integers(min_value=0)),
    )


type MockSpec = list[str] | object | type[object] | None  # stolen from typeshed.


def resolve_union_spec(spec: MockSpec) -> MockSpec:
    """Return the first case of a Union, to pass isinstance tests correctly."""
    return get_args(spec)[0] if isinstance(spec, UnionType) else spec


def user_review_request(
    spec: MockSpec = (), *, name: str, html_url: str = "", avatar_url: str = ""
) -> Mock:
    data = {"login": name, "html_url": html_url, "avatar_url": avatar_url}
    user = Mock(SimpleUser, model_dump=Mock((), return_value=data))
    return Mock(resolve_union_spec(spec), requested_reviewer=user)


def team_review_request(spec: MockSpec = (), *, name: str) -> Mock:
    team = Mock(())
    team.name = name
    return Mock(resolve_union_spec(spec), requested_team=team)


def unknown_review_request(spec: MockSpec = ()) -> Mock:
    return Mock(resolve_union_spec(spec))


def review_requests_modifieds() -> st.SearchStrategy[type[ReviewRequestsModified]]:
    # NOTE: using a tuple instead of a list breaks Pyright for some reason.
    return st.sampled_from([
        events.PullRequestReviewRequested,
        events.PullRequestReviewRequestRemoved,
    ])


@st.composite
def user_review_requests(
    draw: st.DrawFn, *, with_pr_metadata: bool = False
) -> ReviewRequestsModified:
    request = user_review_request(
        spec=draw(review_requests_modifieds()),
        name=draw(st.text()),
        html_url=draw(st.text()),
        avatar_url=draw(st.text()),
    )
    if with_pr_metadata:
        add_pr_metadata(request, draw(st.integers(min_value=1)))
    return request


@st.composite
def team_review_requests(
    draw: st.DrawFn, *, with_pr_metadata: bool = False
) -> ReviewRequestsModified:
    request = team_review_request(
        spec=draw(review_requests_modifieds()), name=draw(st.text())
    )
    if with_pr_metadata:
        add_pr_metadata(request, draw(st.integers(min_value=1)))
    return request


@st.composite
def unknown_review_requests(
    draw: st.DrawFn, *, with_pr_metadata: bool = False
) -> ReviewRequestsModified:
    request = unknown_review_request(spec=draw(review_requests_modifieds()))
    if with_pr_metadata:
        add_pr_metadata(request, draw(st.integers(min_value=1)))
    return request


def review_request_modification_events(
    *,
    with_pr_metadata: bool = False,
    include_unknowns: bool = True,
) -> st.SearchStrategy[ReviewRequestsModified]:
    requests = team_review_requests(
        with_pr_metadata=with_pr_metadata
    ) | user_review_requests(with_pr_metadata=with_pr_metadata)
    if include_unknowns:
        requests = unknown_review_requests(with_pr_metadata=with_pr_metadata) | requests
    return requests


def dummy_user(name: str) -> GitHubUser:
    return GitHubUser(login=name, url="", icon_url="")


def add_pr_metadata(mock: Mock, pr_number: int) -> Mock:
    """Mutates then returns `mock`."""
    mock.pull_request = Mock((), number=pr_number)
    mock.sender = Mock((), id=DEFAULT_PR_SENDER_ID)
    return mock
