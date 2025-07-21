import datetime as dt
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import discord as dc
import pytest

from app.utils import (
    Account,
    aenumerate,
    dynamic_timestamp,
    is_attachment_only,
    is_dm,
    is_helper,
    is_mod,
    post_has_tag,
    post_is_solved,
    truncate,
)


@pytest.mark.parametrize(("type_", "result"), [(dc.Member, False), (dc.User, True)])
def test_is_dm(type_: type[Account], result: bool) -> None:
    assert is_dm(Mock(type_)) == result


def test_is_mod(monkeypatch: pytest.MonkeyPatch, bot_env: SimpleNamespace) -> None:
    monkeypatch.setattr("app.utils.config", bot_env)
    fake_member = SimpleNamespace(
        get_role=lambda role: role if role == bot_env.MOD_ROLE_ID else None
    )
    assert is_mod(cast("dc.Member", fake_member))


@pytest.mark.parametrize(
    "id_",
    [
        1234124125125,
        12846791824,
        12749801924,
        -1,
        0,
        1274687918204,
        19267480912409,
        2**200,
        9999999999999999999999999,
        1756274809124124,
    ],
)
def test_is_not_mod(
    id_: int, monkeypatch: pytest.MonkeyPatch, bot_env: SimpleNamespace
) -> None:
    monkeypatch.setattr("app.utils.config", bot_env)
    fake_member = SimpleNamespace(get_role=lambda role: role if role == id_ else None)
    assert id_ != bot_env.MOD_ROLE_ID
    assert not is_mod(cast("dc.Member", fake_member))


def test_is_helper(monkeypatch: pytest.MonkeyPatch, bot_env: SimpleNamespace) -> None:
    monkeypatch.setattr("app.utils.config", bot_env)
    fake_member = SimpleNamespace(
        get_role=lambda role: role if role == bot_env.HELPER_ROLE_ID else None
    )
    assert is_helper(cast("dc.Member", fake_member))


@pytest.mark.parametrize(
    "id_",
    [
        82980394892387980,
        1253687810294082,
        5627980395172,
        173980942184,
        0,
        -1,
        178409128412498124,
        9999999999999999999999999,
        10**50,
    ],
)
def test_is_not_helper(
    id_: int, monkeypatch: pytest.MonkeyPatch, bot_env: SimpleNamespace
) -> None:
    monkeypatch.setattr("app.utils.config", bot_env)
    fake_member = SimpleNamespace(get_role=lambda role: role if role == id_ else None)
    assert id_ != bot_env.HELPER_ROLE_ID
    assert not is_helper(cast("dc.Member", fake_member))


@pytest.mark.parametrize(
    ("tag", "result"),
    [
        ("foo", True),
        ("bar", True),
        ("baz", False),
        ("lorem", True),
        ("ipsum", True),
        ("dolor", False),
        ("sit", False),
        ("not", True),
        ("mac", True),
        ("windows", False),
    ],
)
def test_post_has_tag(tag: str, result: bool) -> None:
    tags = [
        dc.ForumTag(name=name)
        for name in ("foo", "bar", "Lorem", "ipSUM", "NOT_ISSUE", "macos", "linux")
    ]
    assert (
        post_has_tag(cast("dc.Thread", SimpleNamespace(applied_tags=tags)), tag)
        == result
    )


@pytest.mark.parametrize(
    "names",
    [
        ["solved"],
        ["solved", "solved", "solved"],
        ["solved", "duplicate", "linux"],
        ["Moved to GitHub!", "linux"],
        ["very stale"],
        ["too stale to look at", "macos"],
    ],
)
def test_post_is_solved(names: list[str]) -> None:
    tags = [dc.ForumTag(name=name) for name in names]
    assert post_is_solved(cast("dc.Thread", SimpleNamespace(applied_tags=tags)))


@pytest.mark.parametrize(
    "names",
    [
        ["solving", "linux"],
        ["help"],
        ["other", "meta"],
        ["other", "macos"],
        ["Moved to GitLab", "windows"],
    ],
)
def test_post_is_not_solved(names: list[str]) -> None:
    tags = [dc.ForumTag(name=name) for name in names]
    assert not post_is_solved(cast("dc.Thread", SimpleNamespace(applied_tags=tags)))


@pytest.mark.parametrize(
    "items",
    [
        [1, 2, 3, 4, 5],
        ["spam", "eggs", "bacon", "ham"],
        [False, True, True],
        [{"a": 12}, {"b": 14, "c": 23}, {"d": 183, "e": 21}],
        [..., ..., ...],
        [None, None],
        [[1, 2, 3], [2, 3, 4], [3, 4, 5], [4, 5, 6], [5, 6, 7]],
        [(1, 2, 3), (2, 3, 4), (3, 4, 5), (4, 5, 6), (5, 6, 7)],
    ],
)
@pytest.mark.parametrize("start", [0, 1, 2, 3, 4, 5, -1, -2, -3, -4, -5, 102, -99, 41])
@pytest.mark.asyncio
async def test_aenumerate[T](items: list[T], start: int) -> None:
    async def async_iterator() -> AsyncIterator[T]:
        for item in items:
            yield item

    assert [x async for x in aenumerate(async_iterator(), start)] == list(
        enumerate(items, start)
    )


@pytest.mark.parametrize(
    ("attachments", "content", "preprocessed_content", "embeds", "result"),
    [
        ([], "", None, [], False),
        ([1], "", None, [], True),
        ([1, 2, 3], "", None, [], True),
        ([1, 2, 3], "foo", "", [], True),  # The pre-processing removes the content.
        ([1, 2, 3], "", "foo", [], False),
        ([], "", "foo", [], False),
        ([1, 2, 3], "", "", [1, 2], False),
        ([1, 2, 3], "", "foo", [1, 2], False),
        ([1, 2, 3], "foo", "bar", [], False),
        ([1, 2, 3], "foo", "bar", [1, 2], False),
    ],
)
def test_is_attachment_only(
    attachments: list[int],
    content: str,
    preprocessed_content: str | None,
    embeds: list[int],
    result: bool,
) -> None:
    # NOTE: we don't actually care about having real Discord objects here, we
    # only care about whether they are truthy, so ints are used everywhere.
    fake_message = SimpleNamespace(
        attachments=attachments,
        components=[],
        content=content,
        preprocessed_content=preprocessed_content,
        embeds=embeds,
        poll=None,
        stickers=[],
    )
    assert (
        is_attachment_only(
            cast("dc.Message", fake_message), preprocessed_content=preprocessed_content
        )
        == result
    )


@pytest.mark.parametrize(
    ("s", "length", "suffix", "result"),
    [
        ("aaaaaaaaaaaaaaa", 10, "", "aaaaaaaaaa"),
        ("the quick brown fox", 4, "!", "the!"),
        ("aaaaaaaaaaaaaaa", 10, "…", "aaaaaaaaa…"),
        ("", 10, "…", ""),
        ("aaaaaaaa", 10, "bbbbb", "aaaaaaaa"),
        ("aaaaaaaaaaaaaaa", 10, "...", "aaaaaaa..."),
    ],
)
def test_truncate(s: str, length: int, suffix: str, result: str) -> None:
    assert truncate(s, length, suffix=suffix) == result


@pytest.mark.parametrize(
    ("dt", "fmt", "result"),
    [
        (dt.datetime(2012, 4, 12, 15, 10, 14, tzinfo=dt.UTC), None, "<t:1334243414>"),
        (dt.datetime(2018, 1, 20, 3, 11, 33, tzinfo=dt.UTC), "R", "<t:1516417893:R>"),
        (dt.datetime(1, 1, 1, 1, 1, 1, tzinfo=dt.UTC), "a", "<t:-62135593139:a>"),
        (
            dt.datetime(9999, 12, 31, 23, 59, 59, tzinfo=dt.UTC),
            "Q",
            "<t:253402300799:Q>",
        ),
    ],
)
def test_dynamic_timestamp(dt: dt.datetime, fmt: str | None, result: str) -> None:
    assert dynamic_timestamp(dt, fmt) == result
