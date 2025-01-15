import datetime as dt
from typing import Literal, Protocol, cast

from githubkit.exception import RequestFailed

from app.setup import config, gh

from .discussions import get_discussion

type RepoName = Literal["web", "bot", "main"]
type CacheKey = tuple[RepoName, int]
type EntityKind = Literal["Pull Request", "Issue", "Discussion"]


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
        repo_path = (config.GITHUB_ORG, config.GITHUB_REPOS[repo_name])
        try:
            entity = gh.rest.issues.get(*repo_path, entity_id).parsed_data
            kind = "Issue"
            if entity.pull_request:
                entity = gh.rest.pulls.get(*repo_path, entity_id).parsed_data
                kind = "Pull Request"
        except RequestFailed:
            entity = get_discussion(*repo_path, entity_id)
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
