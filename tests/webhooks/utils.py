from unittest.mock import Mock

from githubkit.versions.latest.models import SimpleUser

from app.components.github_integration.webhooks.prs import PRLike


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
