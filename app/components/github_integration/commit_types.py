import copy
from typing import TYPE_CHECKING, NamedTuple, final

from githubkit.exception import RequestFailed

from app.components.github_integration.models import GitHubUser

if TYPE_CHECKING:
    import datetime as dt

    from toolbox.misc import GH


class CommitKey(NamedTuple):
    owner: str
    repo: str
    sha: str


class CommitSummary(NamedTuple):
    sha: str
    author: GitHubUser | None
    committer: GitHubUser | None
    message: str
    additions: int
    deletions: int
    files_changed: int
    url: str
    date: dt.datetime | None
    signed: bool


@final
class CommitCache:
    def __init__(self, gh: GH) -> None:
        self._gh: GH = gh
        self._cache: dict[CommitKey, CommitSummary] = {}

    def _filter_prefix(self, prefix: str) -> list[CommitKey]:
        return [key for key in self._cache if key.sha.startswith(prefix)]

    async def get(self, key: CommitKey) -> CommitSummary | None:
        match self._filter_prefix(key.sha):
            case []:
                return await self._fetch(key)
            case [full_sha]:
                return self._cache.get(full_sha)
            case _:
                # Behave like GitHub: treat ambiguous short SHAs as invalid
                return None

    async def _fetch(self, key: CommitKey) -> CommitSummary | None:
        try:
            resp = await self._gh.rest.repos.async_get_commit(*key)
        except RequestFailed:
            return None
        obj = resp.parsed_data
        stats = obj.stats or 0
        commit_summary = CommitSummary(
            sha=obj.sha,
            author=GitHubUser(**a.model_dump()) if (a := obj.author) else None,
            committer=GitHubUser(**c.model_dump()) if (c := obj.committer) else None,
            message=obj.commit.message,
            additions=stats and (stats.additions or 0),
            deletions=stats and (stats.deletions or 0),
            files_changed=len(obj.files or ()),
            url=obj.html_url,
            date=(c := obj.commit.committer) and (c.date or None),
            signed=bool((v := obj.commit.verification) and v.verified),
        )
        key_with_full_sha = copy.replace(key, sha=obj.sha)
        self._cache[key_with_full_sha] = commit_summary
        return commit_summary
