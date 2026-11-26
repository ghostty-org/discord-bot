import asyncio
from unittest.mock import AsyncMock, Mock

import discord as dc
import pytest

from app.bot import GhosttyBot, emojis


def make_emoji(name: str) -> Mock:
    emoji = Mock(dc.Emoji)
    emoji.name = name
    return emoji


def make_bot() -> Mock:
    bot = Mock(GhosttyBot)
    bot.emojis_loaded = asyncio.Event()
    bot._emojis = {}
    return bot


@pytest.mark.anyio
async def test_load_emojis_uses_application_emojis() -> None:
    known = make_emoji("commit")
    unknown = make_emoji("not_a_real_emoji")
    bot = make_bot()
    bot.fetch_application_emojis = AsyncMock(return_value=[known, unknown])

    await GhosttyBot.load_emojis(bot)

    bot.fetch_application_emojis.assert_awaited_once_with()
    assert bot._emojis["commit"] is known
    assert "not_a_real_emoji" not in bot._emojis
    assert bot.emojis_loaded.is_set()


@pytest.mark.anyio
async def test_load_emojis_sets_event_on_failure() -> None:
    bot = make_bot()
    bot.fetch_application_emojis = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await GhosttyBot.load_emojis(bot)

    assert bot.emojis_loaded.is_set()


def test_emojis_default_to_fallback() -> None:
    assert emojis()["commit"] == "❓"
