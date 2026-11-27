from typing import TYPE_CHECKING

from app.config import PRIVATE_REPOS, config

if TYPE_CHECKING:
    import discord as dc


def can_link_repo(message: dc.Message, owner: str, repo: str) -> bool:
    """Whether the message can lead to the bot exposing data about this repo."""
    if owner.casefold() != "ghostty-org":
        return True
    if repo.casefold() not in PRIVATE_REPOS:
        return True
    if message.guild is None:  # Probably unreachable in practice
        return False

    member = message.guild.get_member(message.author.id)
    return member is not None and config().is_privileged_github(member)
