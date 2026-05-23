import asyncio
import subprocess
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.utils import any_comparables

from toolbox.misc import (
    aenumerate,
    async_process_check_output,
    drain_queue,
    seq_to_aiter,
    truncate,
)


@given(st.lists(any_comparables()))
async def test_seq_to_aiter(elems: list[object]) -> None:
    assert [e async for e in seq_to_aiter(elems)] == elems


@given(st.lists(any_comparables()), st.integers())
async def test_aenumerate(elems: list[object], start: int) -> None:
    result = [e async for e in aenumerate(seq_to_aiter(elems), start)]
    assert result == list(enumerate(elems, start))


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


@given(st.lists(any_comparables()))
async def test_drain_queue(elems: list[object]) -> None:
    queue = asyncio.Queue[object]()

    async def producer() -> None:
        for e in elems:
            await queue.put(e)
        queue.shutdown()

    async def consumer() -> None:
        async for i, e in aenumerate(drain_queue(queue)):
            assert e == elems[i]

    async with asyncio.TaskGroup() as group:
        group.create_task(producer())
        group.create_task(consumer())

    with pytest.raises(asyncio.QueueShutDown):
        await queue.get()
