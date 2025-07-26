# pyright: reportPrivateUsage=false
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, cast

import pytest

from tests.fixtures.hooks import TrackedCallable
from tests.hooks.utils import spawn_bot_message, spawn_user_message

if TYPE_CHECKING:
    from unittest.mock import Mock

    from tests.fixtures.hooks import DeleteHook

    from app.common.hooks import MessageLinker


@pytest.mark.asyncio
async def test_original_delete(linker: MessageLinker, delete_hook: DeleteHook) -> None:
    msg = spawn_user_message()
    reply = cast("Mock", spawn_bot_message())
    reply.delete = TrackedCallable(lambda: delete_hook(reply))
    linker.link(msg, reply)

    await delete_hook(msg)

    assert reply.delete.called
    assert not linker._refs


@pytest.mark.asyncio
async def test_original_delete_frozen(
    linker: MessageLinker, delete_hook: DeleteHook
) -> None:
    msg = spawn_user_message()
    reply = cast("Mock", spawn_bot_message())
    linker.link(msg, reply)
    linker.freeze(msg)

    await delete_hook(msg)

    assert linker._refs
    assert not reply.delete.called
    assert not linker.is_frozen(msg)


@pytest.mark.parametrize("freeze", [True, False])
@pytest.mark.asyncio
async def test_original_delete_not_linked(
    linker: MessageLinker, delete_hook: DeleteHook, freeze: bool
) -> None:
    msg = spawn_user_message()
    if freeze:
        linker.freeze(msg)

    assert linker.is_frozen(msg) is freeze
    await delete_hook(msg)

    assert not linker.is_frozen(msg)


@pytest.mark.asyncio
async def test_original_delete_expired(
    linker: MessageLinker, delete_hook: DeleteHook
) -> None:
    msg = spawn_user_message(age=dt.timedelta(days=2))
    reply = cast("Mock", spawn_bot_message())
    linker.link(msg, reply)

    await delete_hook(msg)

    assert not reply.delete.called
    assert not linker._refs


@pytest.mark.asyncio
async def test_reply_delete(linker: MessageLinker, delete_hook: DeleteHook) -> None:
    msg = spawn_user_message()
    reply = spawn_bot_message()
    linker.link(msg, reply)
    linker.freeze(msg)

    await delete_hook(reply)

    assert not linker._refs
    assert not linker.is_frozen(msg)


@pytest.mark.asyncio
async def test_bot_not_linked_delete(
    linker: MessageLinker, delete_hook: DeleteHook
) -> None:
    msg = spawn_bot_message()
    linker.freeze(msg)

    await delete_hook(msg)

    assert not linker.is_frozen(msg)
