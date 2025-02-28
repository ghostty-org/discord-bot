import re
from collections.abc import AsyncIterator
from contextlib import suppress

from githubkit.exception import RequestFailed

from app.components.entity_mentions.cache import TTRCache
from app.setup import config, gh

ENTITY_REGEX = re.compile(
    r"(?P<owner>\b[a-z0-9\-]+/)?"
    r"(?P<repo>\b[a-z0-9\-\._]+)?"
    r"#(?P<number>\d{1,6})(?!\.\d)\b",
    re.IGNORECASE,
)

CODEBLOCK_REGEX = re.compile(r"```.*?```", re.DOTALL)


class OwnerCache(TTRCache[str, str]):
    async def fetch(self, key: str) -> None:
        self[key] = await find_repo_owner(key)


owner_cache = OwnerCache(3600)  # 1 hour


def has_entity_mention(content: str) -> bool:
    text_outside_codeblocks = CODEBLOCK_REGEX.sub("", content)

    return ENTITY_REGEX.search(text_outside_codeblocks) is not None


async def find_repo_owner(name: str) -> str:
    resp = await gh.rest.search.async_repos(
        q=name, sort="stars", order="desc", per_page=20
    )
    return next(
        r.owner.login
        for r in resp.parsed_data.items
        if r.name == name and r.owner is not None
    )


async def resolve_repo_signatures(content: str) -> AsyncIterator[tuple[str, str, int]]:
    valid_signatures = 0
    for match in ENTITY_REGEX.finditer(content):
        owner, repo, number = match["owner"], match["repo"], int(match["number"])
        match owner, repo:
            case None, None if number < 10:
                # Ignore single-digit mentions like #1, (likely a false positive)
                continue
            case None, None:
                # Standard Ghostty mention, e.g. #2354
                yield config.GITHUB_ORG, config.GITHUB_REPOS["main"], number
            case None, "main" | "web" | "bot" as repo:
                # Special ghostty-org prefixes
                yield config.GITHUB_ORG, config.GITHUB_REPOS[repo], number
            case None, repo:
                # Only a name provided, e.g. uv#8020.
                with suppress(RequestFailed, RuntimeError):
                    yield await owner_cache.get(repo), repo, number
            case owner, None:
                # Invalid case, e.g. trag1c/#123
                continue
            case owner, repo:
                # Any public repo, e.g. trag1c/ixia#33.
                yield owner.rstrip("/"), repo, number
        valid_signatures += 1
        if valid_signatures == 10:
            break
