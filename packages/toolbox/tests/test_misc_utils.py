import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st

from toolbox.misc import aenumerate, async_process_check_output, truncate

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@given(st.lists(st.from_type(type)), st.integers())
async def test_aenumerate[T](items: list[T], start: int) -> None:
    async def async_iterator() -> AsyncGenerator[T]:
        for item in items:
            yield item

    assert [x async for x in aenumerate(async_iterator(), start)] == list(
        enumerate(items, start)
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
