import datetime as dt
from abc import ABC, abstractmethod

from githubkit.exception import RequestFailed

from .discussions import get_discussion
from .models import Entity, Issue, PullRequest
from app.setup import gh

type CacheKey = tuple[str, str, int]


class TTRCache[KT, VT](ABC):
    def __init__(self, ttr: int) -> None:
        self._ttr = dt.timedelta(seconds=ttr)
        self._cache: dict[KT, tuple[dt.datetime, VT]] = {}

    def __contains__(self, key: KT) -> bool:
        return key in self._cache

    def __getitem__(self, key: KT) -> tuple[dt.datetime, VT]:
        return self._cache[key]

    def __setitem__(self, key: KT, value: VT) -> None:
        self._cache[key] = (dt.datetime.now(tz=dt.UTC), value)

    @abstractmethod
    async def fetch(self, key: KT) -> None:
        pass

    async def _refresh(self, key: KT) -> None:
        if key not in self:
            await self.fetch(key)
            return
        timestamp, *_ = self[key]
        if dt.datetime.now(tz=dt.UTC) - timestamp >= self._ttr:
            await self.fetch(key)

    async def get(self, key: KT) -> VT:
        await self._refresh(key)
        _, value = self[key]
        return value


class EntityCache(TTRCache[CacheKey, Entity]):
    async def fetch(self, key: CacheKey) -> None:
        try:
            issue = (await gh.rest.issues.async_get(*key)).parsed_data
            if issue.pull_request:
                pull = (await gh.rest.pulls.async_get(*key)).parsed_data
                self[key] = PullRequest.model_validate(pull, from_attributes=True)
            else:
                self[key] = Issue.model_validate(issue, from_attributes=True)
        except RequestFailed:
            self[key] = await get_discussion(*key)


entity_cache = EntityCache(1800)  # 30 minutes
