import datetime as dt
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

import discord as dc
import pytest
from hypothesis import given
from hypothesis import strategies as st

from toolbox.discord import (
    Account,
    dynamic_timestamp,
    format_or_file,
    is_dm,
    post_has_tag,
    post_is_solved,
    pretty_print_account,
    suppress_embeds_after_delay,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize(("type_", "result"), [(dc.Member, False), (dc.User, True)])
def test_is_dm(type_: type[Account], result: bool) -> None:
    assert is_dm(Mock(type_)) == result


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
    assert post_has_tag(Mock(dc.Thread, applied_tags=tags), tag) == result


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
    assert post_is_solved(Mock(dc.Thread, applied_tags=tags))


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
    assert not post_is_solved(Mock(dc.Thread, applied_tags=tags))


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


async def test_suppress_embeds_after_delay() -> None:
    suppressed = False

    async def edit(**kwargs: Any) -> None:
        nonlocal suppressed
        suppressed = kwargs.get("suppress", False)

    fake_message = Mock(dc.Message, edit=edit)

    await suppress_embeds_after_delay(fake_message, 0)

    assert suppressed


@pytest.mark.parametrize(
    ("content", "template", "transform", "result"),
    [
        ("hi", None, None, "hi"),
        ("hi", "{}!", None, "hi!"),
        (
            "HI EVER— I mean, hi everyone!",
            None,
            str.swapcase,
            "hi ever— i MEAN, HI EVERYONE!",
        ),
        ("hello", "# ~~{}!~~", str.swapcase, "# ~~HELLO!~~"),
    ],
)
def test_format_or_file_short(
    content: str, template: str | None, transform: Callable[[str], str], result: str
) -> None:
    assert format_or_file(
        content,
        template=template,
        transform=transform,
    ) == (result, None)


def test_format_or_file_long() -> None:
    content, file = format_or_file("a" * 10000)
    assert not content
    assert file
    assert file.fp.read() == b"a" * 10000


def test_format_or_file_long_template() -> None:
    content, file = format_or_file("a" * 2001, template="not {}")
    assert content == "not "
    assert file
    assert file.fp.read() == b"a" * 2001


def test_format_or_file_long_transform() -> None:
    content, file = format_or_file("a" * 4321, transform=str.swapcase)
    assert not content
    assert file
    assert file.fp.read() == b"a" * 4321


def test_format_or_file_long_template_transform() -> None:
    content, file = format_or_file("a" * 5000, template="# {}!", transform=str.swapcase)
    assert content == "# !"
    assert file
    assert file.fp.read() == b"a" * 5000


@given(st.text(), st.integers())
def test_pretty_print_account(name: str, id_: int) -> None:
    fake_account = Mock(Account, id=id_)
    fake_account.name = name
    output = pretty_print_account(fake_account)
    assert name in output
    assert str(id_) in output
