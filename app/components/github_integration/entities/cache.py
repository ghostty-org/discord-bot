from typing import TYPE_CHECKING, final, override

from githubkit.exception import RequestFailed
from loguru import logger

from .discussions import get_discussion
from app.components.github_integration.models import Entity, Issue, PullRequest
from toolbox.cache import TTRCache

if TYPE_CHECKING:
    from discord.ext import commands

    from toolbox.misc import GH


type EntitySignature = tuple[str, str, int]


@final
class EntityCache(TTRCache[EntitySignature, Entity]):
    """
    WARNING: cogs that use this cache MUST register a GitHub client with register_gh;
    behavior is undefined if not done. Furthermore, they MUST unregister their client
    with unregister_gh on unload; behavior is undefined if not done. Finally, if
    multiple cogs register a client, it is undefined which client will be used, but
    clients of unloaded cogs will not be used; this will not be an issue if one client
    is used by all cogs.
    """

    def __init__(self, **ttr: float) -> None:
        super().__init__(**ttr)
        self._current_gh: GH | None = None
        self._registered_ghs: dict[commands.Cog, GH] = {}

    @override
    async def fetch(self, key: EntitySignature) -> None:
        try:
            entity = (await self.gh.rest.issues.async_get(*key)).parsed_data
            model = Issue
            if entity.pull_request:
                entity = (await self.gh.rest.pulls.async_get(*key)).parsed_data
                model = PullRequest
            self[key] = model.model_validate(entity, from_attributes=True)
        except RequestFailed:
            if discussion := await get_discussion(self.gh, *key):
                self[key] = discussion

    @property
    def gh(self) -> GH:
        if gh := next(iter(self._registered_ghs.values()), None):
            logger.trace("found registered gh")
            return gh
        msg = "entity cache used while all users' cogs are unloaded"
        raise AssertionError(msg)

    def register_gh(self, cog: commands.Cog, gh: GH) -> None:
        self._registered_ghs[cog] = gh
        logger.debug("registered gh for cog {} (0x{:x})", type(cog).__name__, id(cog))

    def unregister_gh(self, cog: commands.Cog) -> None:
        del self._registered_ghs[cog]
        logger.debug("unregistered gh for cog {} (0x{:x})", type(cog).__name__, id(cog))


entity_cache = EntityCache(minutes=30)
