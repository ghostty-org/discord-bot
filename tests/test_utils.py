import datetime as dt
import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import Mock

import discord as dc
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from app.config import config
from app.utils import (
    aenumerate,
    async_process_check_output,
    dynamic_timestamp,
    format_diff_note,
    format_or_file,
    is_attachment_only,
    is_dm,
    is_helper,
    is_mod,
    post_has_tag,
    post_is_solved,
    pretty_print_account,
    suppress_embeds_after_delay,
    truncate,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from app.utils import Account


@pytest.mark.parametrize(("type_", "result"), [(dc.Member, False), (dc.User, True)])
def test_is_dm(type_: type[Account], result: bool) -> None:
    assert is_dm(Mock(type_)) == result


def test_is_mod() -> None:
    fake_member = SimpleNamespace(
        get_role=lambda role: role if role == config.mod_role_id else None
    )
    assert is_mod(cast("dc.Member", fake_member))


@given(st.integers().filter(lambda id_: id_ != config.mod_role_id))
def test_is_not_mod(id_: int) -> None:
    fake_member = SimpleNamespace(get_role=lambda role: role if role == id_ else None)
    assert not is_mod(cast("dc.Member", fake_member))


def test_is_helper() -> None:
    fake_member = SimpleNamespace(
        get_role=lambda role: role if role == config.helper_role_id else None
    )
    assert is_helper(cast("dc.Member", fake_member))


@given(st.integers().filter(lambda id_: id_ != config.helper_role_id))
def test_is_not_helper(id_: int) -> None:
    fake_member = SimpleNamespace(get_role=lambda role: role if role == id_ else None)
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


@given(st.lists(st.from_type(type)), st.integers())
async def test_aenumerate[T](items: list[T], start: int) -> None:
    async def async_iterator() -> AsyncGenerator[T]:
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
    # NOTE: we don't actually care about having real Discord objects here, we only care
    # about whether they are truthy, so ints are used everywhere.
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


async def test_suppress_embeds_after_delay() -> None:
    suppressed = False

    async def edit(**kwargs: Any) -> None:
        nonlocal suppressed
        suppressed = kwargs.get("suppress", False)

    fake_message = cast("dc.Message", SimpleNamespace(edit=edit))

    await suppress_embeds_after_delay(fake_message, 0)

    assert suppressed


@given(st.integers(), st.integers(), st.integers())
def test_format_diff_note(additions: int, deletions: int, changed_files: int) -> None:
    assume(changed_files and (additions or deletions))
    formatted = format_diff_note(additions, deletions, changed_files)
    assert formatted is not None
    assert f"+{additions}" in formatted
    assert f"-{deletions}" in formatted
    assert str(changed_files) in formatted


def test_format_diff_note_unavailable() -> None:
    assert format_diff_note(0, 0, 0) is None


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
    content: str,
    template: str | None,
    transform: Callable[[str], str],
    result: str,
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


@pytest.mark.skipif(not sys.executable, reason="cannot find python interpreter path")
@pytest.mark.parametrize(
    ("code", "output"),
    [
        ("print('Hello, world!')", "Hello, world!\n"),
        ("", ""),
        ("import sys; print('Hello, world!', file=sys.stderr)", ""),
    ],
)
async def test_async_process_check_output_succeeds(code: str, output: str) -> None:
    stdout = await async_process_check_output(sys.executable, "-c", code)
    assert stdout == output


@pytest.mark.skipif(not sys.executable, reason="cannot find python interpreter path")
async def test_async_process_check_output_fails() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        await async_process_check_output(
            sys.executable, "-c", "import sys; sys.exit(1)"
        )


async def test_async_process_check_output_invalid_argument() -> None:
    with pytest.raises(ValueError, match="stdout argument not allowed"):
        await async_process_check_output("", stdout=subprocess.DEVNULL)


@given(st.text(), st.integers())
def test_pretty_print_account(name: str, id_: int) -> None:
    fake_account = cast("Account", SimpleNamespace(name=name, id=id_))
    output = pretty_print_account(fake_account)
    assert name in output
    assert str(id_) in output
