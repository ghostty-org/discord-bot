import datetime as dt
from abc import ABC, abstractmethod

from loguru import logger

__all__ = ("TTRCache",)


class TTRCache[KT, VT](ABC):
    _ttr: dt.timedelta

    def __init__(self, **ttr: float) -> None:
        """Keyword arguments are passed to datetime.timedelta."""
        self._ttr = dt.timedelta(**ttr)
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
            logger.debug("{} not in cache; fetching", key)
            await self.fetch(key)
            return
        timestamp, *_ = self[key]
        if dt.datetime.now(tz=dt.UTC) - timestamp >= self._ttr:
            logger.debug("refreshing outdated key {}", key)
            await self.fetch(key)

    async def get(self, key: KT) -> VT | None:
        await self._refresh(key)
        try:
            _, value = self[key]
        except KeyError:
            return None
        return value
