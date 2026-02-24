from typing import final, override

from githubkit.exception import RequestFailed

from .discussions import get_discussion
from app.components.github_integration.models import Entity, Issue, PullRequest
from app.config import gh
from toolbox.cache import TTRCache

type EntitySignature = tuple[str, str, int]


@final
class EntityCache(TTRCache[EntitySignature, Entity]):
    @override
    async def fetch(self, key: EntitySignature) -> None:
        try:
            entity = (await gh().rest.issues.async_get(*key)).parsed_data
            model = Issue
            if entity.pull_request:
                entity = (await gh().rest.pulls.async_get(*key)).parsed_data
                model = PullRequest
            self[key] = model.model_validate(entity, from_attributes=True)
        except RequestFailed:
            if discussion := await get_discussion(*key):
                self[key] = discussion


entity_cache = EntityCache(minutes=30)
