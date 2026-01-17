from typing import final, override

from githubkit.exception import RequestFailed

from .discussions import get_discussion
from app.components.github_integration.models import Entity, Issue, PullRequest
from toolbox.cache import ExtensibleTTRCache
from toolbox.misc import GH

type EntitySignature = tuple[str, str, int]


@final
class EntityCache(ExtensibleTTRCache[EntitySignature, Entity, GH]):
    @override
    async def efetch(self, key: EntitySignature, extra: GH) -> None:
        gh = extra
        try:
            entity = (await gh.rest.issues.async_get(*key)).parsed_data
            model = Issue
            if entity.pull_request:
                entity = (await gh.rest.pulls.async_get(*key)).parsed_data
                model = PullRequest
            self[key] = model.model_validate(entity, from_attributes=True)
        except RequestFailed:
            if discussion := await get_discussion(gh, *key):
                self[key] = discussion


entity_cache = EntityCache(minutes=30)
