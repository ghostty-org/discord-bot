# pyright: reportPrivateUsage=false
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from tests.hooks.utils import spawn_message

if TYPE_CHECKING:
    import discord as dc

    from app.common.hooks import MessageLinker


def test_double_link_fails(linker: MessageLinker) -> None:
    msg = spawn_message(id=1)
    linker.link(msg, msg)

    with pytest.raises(ValueError, match="message 1 already has a reply linked"):
        linker.link(msg, msg)


def test_message_expiry(linker: MessageLinker) -> None:
    msg = spawn_message()
    msg2 = spawn_message(age=dt.timedelta(days=2))

    assert not linker.is_expired(msg)
    assert linker.is_expired(msg2)


def test_linker_retrieve_original_message(linker: MessageLinker) -> None:
    msg = spawn_message()
    msg2 = spawn_message()
    linker.link(msg, msg2)

    assert linker.get_original_message(msg) is None
    assert linker.get_original_message(msg2) == msg

    linker.unlink(msg2)
    assert linker._refs

    linker.unlink_from_reply(msg2)
    assert not linker._refs


def test_free_dangling_links(linker: MessageLinker) -> None:
    expected_to_stay: list[dc.Message] = []
    expected_to_go: list[dc.Message] = []
    for h in range(48):
        msg = spawn_message(age=dt.timedelta(hours=h))
        linker._refs[msg] = msg
        linker.freeze(msg)
        (expected_to_stay if h < 24 else expected_to_go).append(msg)

    linker.link(msg := spawn_message(), msg)

    for msg in expected_to_stay:
        assert msg in linker._refs
        assert linker.is_frozen(msg)
    for msg in expected_to_go:
        assert msg not in linker._refs
        assert not linker.is_frozen(msg)
