from typing import TYPE_CHECKING

from app.config import PRIVATE_REPOS, config

if TYPE_CHECKING:
    from toolbox.discord import Account


def can_link_repo(author: Account, owner: str, repo: str) -> bool:
    """Whether the message author may make the bot expose data from this repo."""
    if owner.casefold() != "ghostty-org":
        return True
    if repo.casefold() not in PRIVATE_REPOS:
        return True

    member = config().ghostty_guild.get_member(author.id)
    return member is not None and config().is_privileged_github(member)
