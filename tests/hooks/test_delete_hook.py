import datetime as dt
from typing import TYPE_CHECKING, cast

import pytest

from tests.fixtures.hooks import TrackedCallable
from tests.hooks.utils import spawn_bot_message, spawn_user_message

if TYPE_CHECKING:
    from unittest.mock import Mock

    from app.common.linker import MessageLinker


async def test_original_delete(linker: MessageLinker) -> None:
    msg = spawn_user_message()
    reply = cast("Mock", spawn_bot_message())
    reply.delete = TrackedCallable(lambda: linker.delete(reply))
    linker.link(msg, reply)

    await linker.delete(msg)

    assert reply.delete.called
    assert not linker.refs


async def test_original_delete_frozen(linker: MessageLinker) -> None:
    msg = spawn_user_message()
    reply = cast("Mock", spawn_bot_message())
    linker.link(msg, reply)
    linker.freeze(msg)

    await linker.delete(msg)

    assert linker.refs
    assert not reply.delete.called
    assert not linker.is_frozen(msg)


@pytest.mark.parametrize("freeze", [True, False])
async def test_original_delete_not_linked(linker: MessageLinker, freeze: bool) -> None:
    msg = spawn_user_message()
    if freeze:
        linker.freeze(msg)

    assert linker.is_frozen(msg) is freeze
    await linker.delete(msg)

    assert not linker.is_frozen(msg)


async def test_original_delete_expired(linker: MessageLinker) -> None:
    msg = spawn_user_message(age=dt.timedelta(days=2))
    reply = cast("Mock", spawn_bot_message())
    linker.link(msg, reply)

    await linker.delete(msg)

    assert not reply.delete.called
    assert not linker.refs


async def test_reply_delete(linker: MessageLinker) -> None:
    msg = spawn_user_message()
    reply = spawn_bot_message()
    linker.link(msg, reply)
    linker.freeze(msg)

    await linker.delete(reply)

    assert not linker.refs
    assert not linker.is_frozen(msg)


async def test_bot_not_linked_delete(linker: MessageLinker) -> None:
    msg = spawn_bot_message()
    linker.freeze(msg)

    await linker.delete(msg)

    assert not linker.is_frozen(msg)
