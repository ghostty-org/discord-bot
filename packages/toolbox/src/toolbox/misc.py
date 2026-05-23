import asyncio
import re
import subprocess
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterable, Sequence

__all__ = (
    "COLOR_PALETTE",
    "URL_REGEX",
    "aenumerate",
    "async_process_check_output",
    "drain_queue",
    "seq_to_aiter",
    "truncate",
)

type EmbedColor = Literal["green", "red", "purple", "gray", "orange", "blue"]

COLOR_PALETTE: dict[EmbedColor, int] = {
    "green": 0x3FB950,
    "red": 0xF85149,
    "blue": 0x4C8CED,
    "purple": 0xAB7DF8,
    "gray": 0x9198A1,
    "orange": 0xEDB74A,
}

URL_REGEX = re.compile(
    r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b"
    r"(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)


async def seq_to_aiter[T](elems: Sequence[T]) -> AsyncGenerator[T]:
    """
    Convert any sequence to an asynchronous iterator. Synchronous iterables in general
    aren't supported as this function doesn't magically insert await points into
    them—computing the elements would block the scheduler until it finishes if it takes
    a nontrivial amount of time!
    """
    for elem in elems:
        yield elem


def truncate(s: str, length: int, *, suffix: str = "…") -> str:
    if len(s) <= length:
        return s
    return s[: length - len(suffix)] + suffix


async def aenumerate[T](
    it: AsyncIterable[T], start: int = 0
) -> AsyncGenerator[tuple[int, T]]:
    i = start
    async for x in it:
        yield i, x
        i += 1


async def async_process_check_output(program: str, *args: str, **kwargs: Any) -> str:
    if "stdout" in kwargs:
        msg = "stdout argument not allowed: it would be overridden"
        raise ValueError(msg)
    proc = await asyncio.create_subprocess_exec(
        program, *args, stdout=subprocess.PIPE, **kwargs
    )
    assert proc.stdout is not None  # set to PIPE above
    if rc := await proc.wait():
        raise subprocess.CalledProcessError(
            returncode=rc,
            cmd=[program, *args],
            output=await proc.stdout.read(),
            stderr=proc.stderr and await proc.stderr.read(),
        )
    return (await proc.stdout.read()).decode()


async def drain_queue[T](queue: asyncio.Queue[T]) -> AsyncGenerator[T]:
    """Yield `queue.get()` repeatedly until it has been shut down."""
    with suppress(asyncio.QueueShutDown):
        while True:
            yield await queue.get()
